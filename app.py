# Import necessary libraries
import streamlit as st
import pandas as pd
import openai
import PyPDF2
import io
import openpyxl
import sqlite3
import re

# Apply a custom theme via Streamlit's configuration
st.set_page_config(page_title="Assessment Generator", page_icon=":pencil:", layout="wide")

# Load CSS for additional styling
with open('style.css') as f:
    st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# Setup SQLite database for storing feedback
conn = sqlite3.connect('feedback.db')
c = conn.cursor()
c.execute('''
          CREATE TABLE IF NOT EXISTS feedback (
              id INTEGER PRIMARY KEY,
              rating INTEGER NOT NULL,
              feedback TEXT NOT NULL
          )
          ''')
conn.commit()

@st.cache_data
def read_pdf(file):
    # Read and extract text from a PDF file
    with io.BytesIO(file.getvalue()) as f:
        reader = PyPDF2.PdfReader(f)
        text = ''
        for page in reader.pages:
            text += page.extract_text()
    return text

def estimate_tokens(text):
    # Estimate the number of tokens in the provided text
    words = text.split()
    return len(words) * 1.33  # Approximation: 1.33 words per token

def display_content_with_latex(content):
    """ Function to identify and render LaTeX expressions within the content """
    # Regular expression to detect LaTeX patterns
    latex_patterns = [
        r'\\frac\{.*?\}\{.*?\}',  # Fractions
        r'\$.*?\$',               # Inline math
        r'\\sqrt(?:\{.*?\})?',    # Square root
        r'\\sum(?:_\{.*?\})?(?:\^\{.*?\})?',  # Summation
        r'\\int(?:_\{.*?\})?(?:\^\{.*?\})?',  # Integral
        r'\^\{.*?\}',  # Exponents (Superscripts)
        r'_\{.*?\}',  # Subscripts
        r'\\begin\{.*?matrix\}.*?\\end\{.*?matrix\}',  # Matrices and arrays
        r'\\text\{.*?\}',  # Text formatting in math mode
        r'\\[a-zA-Z]+(?=\W|\Z)',  # Greek letters
        r'\\(?:log|sin|cos|tan|ln|exp|arcsin|arccos|arctan)\b',  # Trig and log functions
        r'\\left[\(\[\{].*?\\right[\)\]\}]',  # Parentheses and Brackets
        r'\\begin\{aligned\}.*?\\end\{aligned\}',  # Aligned equations
        # Add more patterns as needed
    ]
    
    # Compile regex to match any LaTeX pattern
    latex_regex = re.compile('|'.join(latex_patterns))
    
    # Split content into parts based on LaTeX delimiters
    parts = re.split(r'(\$.*?\$|\\frac\{.*?\}\{.*?\}|\\sqrt(?:\{.*?\})?|\\sum(?:_\{.*?\})?(?:\^\{.*?\})?|\\int(?:_\{.*?\})?(?:\^\{.*?\})?|\^\{.*?\}|_\{.*?\}|\\begin\{.*?matrix\}.*?\\end\{.*?matrix\}|\\text\{.*?\}|\\[a-zA-Z]+(?=\W|\Z)|\\(?:log|sin|cos|tan|ln|exp|arcsin|arccos|arctan)\b|\\left[\(\[\{].*?\\right[\)\]\}]|\\begin\{aligned\}.*?\\end\{aligned\})', content)
    
    # Initialize a list to hold processed parts
    processed_parts = []

    for part in parts:
        if latex_regex.search(part):
            processed_parts.append(f"$$ {part.strip()} $$")
        else:
            processed_parts.append(part.strip())

    # Join all processed parts into a single string to maintain proper formatting
    final_content = ' '.join(processed_parts)
    
    # Render the final content with LaTeX where applicable
    st.markdown(final_content)

def convert_latex_to_text(content):
    """Convert LaTeX fractions and other expressions to plain text format for Excel export."""
    # Replace LaTeX fractions with plain text fractions
    content = re.sub(r'\\frac\{(.*?)\}\{(.*?)\}', r'\1/\2', content)
    # You can add more replacements here as needed for other LaTeX expressions
    return content

# Mapping subjects to topics
subject_to_topics = {
    "Mathematics": ["Whole Numbers", "Algebra", "Money", "Measurement and Geometry", "Statistics", "Fractions", "Time", "Area and Volume", "Decimals", "Multiplication and Division", "Percentage", "Ratio", "Rate and Speed"],
    "English Language": ["Grammar", "Literature", "Writing", "Reading Comprehension"],
    "Science": ["Physics", "Chemistry", "Biology"],
    "Social Studies": ["Discovering Self and Immediate Environment", "Understanding Singapore in the Past and Present", "Appreciating Singapore, the Region and the World We Live In"]
}

# Streamlit code to create the UI
def main():
    st.title("Assessment Generator")
    st.subheader("Generate Assessments based on Academic Level and Topics")

    # Form to handle API key input and submission
    with st.form(key="api_form"):
        user_api_key = st.text_input("OpenAI API Key:", type="password")
        submit_button = st.form_submit_button(label="Set API Key")

    if submit_button:
        st.session_state.api_key = user_api_key
        st.success("API key set successfully!")

    if not st.session_state.get('api_key'):
        st.warning("Please enter and confirm your OpenAI API key to continue.")
        st.stop()

    openai.api_key = st.session_state.api_key
    client = openai.OpenAI(api_key=user_api_key)

    # Using columns to organize inputs
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        subject_list = list(subject_to_topics.keys())
        user_input_topic = st.selectbox('Subject', subject_list)

    topics = subject_to_topics.get(user_input_topic, [])
    selected_topics = col2.multiselect('Select Topics (You can choose multiple)', topics)

    with col3:
        acad_levels = ["Primary One", "Primary Two", "Primary Three", "Primary Four", "Primary Five", "Primary Six"]
        user_input_acad_level = st.selectbox('Academic Level', acad_levels)

    col4, col5, col6 = st.columns([1, 1, 3])
    with col4:
        difficulties = ["Basic", "Intermediate", "Advanced"]
        user_input_difficulty = st.selectbox('Question Difficulty', difficulties)

    with col5:
        user_input_no_of_qns = st.number_input("Number of Questions:", min_value=1, max_value=50, value=10)
    
    with col6:
        user_input_keyword = st.text_input("Keywords (Optional): ")

    # Show weightage option only if more than one topic is selected
    if len(selected_topics) > 1:
        specify_weightage = st.checkbox("Specify weightage of topics?")
        weightage_info = {}

        if specify_weightage:
            st.markdown("### Enter the weightage for each selected topic:")
            total_weight = 0

            for topic in selected_topics:
                weight = st.number_input(f"Weightage for {topic} (%)", min_value=0, max_value=100, value=0)
                weightage_info[topic] = weight
                total_weight += weight

            if total_weight != 100:
                st.error("Total weightage must sum up to 100%. Please adjust your inputs.")

    buff, col, buff2 = st.columns([1, 2, 1])
    with col:
        uploaded_file = st.file_uploader("Upload a file (Optional)", type=['txt', 'pdf'])

    file_text = ""
    if uploaded_file is not None:
        if uploaded_file.type == "text/plain":
            file_text = str(uploaded_file.read(), "utf-8")
            st.success("Text file uploaded successfully!")
        elif uploaded_file.type == "application/pdf":
            file_text = read_pdf(uploaded_file)
            st.success("PDF file uploaded successfully!")

        # Estimate tokens and check if it exceeds the model's token limit
        token_count = estimate_tokens(file_text)
        if token_count > 3000:
            st.error(f"The uploaded document is too long ({int(token_count)} tokens). Please reduce the file content (Max tokens = 3000).")
        else:
            st.text_area("File content", file_text, height=250)

    if st.button("Generate Questions"):
        if len(selected_topics) > 1 and specify_weightage and sum(weightage_info.values()) != 100:
            st.error("Please ensure the total weightage sums up to 100% before generating questions.")
        else:
            with st.spinner('Generating questions...'):
                try:
                    if "Any" in selected_topics:
                        # If "Any" is selected, use all topics under the chosen subject
                        selected_topics_str = "Any"
                    else:
                        # Combine selected topics into a single string for the API request
                        selected_topics_str = ", ".join(selected_topics)

                    # Convert weightage information to a string format for the API call
                    weightage_str = ', '.join([f"{topic}: {weight}%" for topic, weight in weightage_info.items()]) if len(selected_topics) > 1 and specify_weightage else "Not specified"

                    # Ensure single API call with correct parameters
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{
                            "role": "user",
                            "content": f"With reference to the content in {file_text}, if any, and topics {selected_topics_str}, generate {user_input_no_of_qns} {user_input_topic} unique assessment or exam-style questions with corresponding answers for the academic level of \
                                {user_input_acad_level} according to the Singapore education system of {user_input_difficulty} difficulty level. Keywords: {user_input_keyword}. \
                                Display only questions and answers without caption or commentary. \
                                Use LaTeX for rendering fractions and algebraic expressions. Present these questions and answers in a format that is clear and readable to users. \
                                Weightage information: {weightage_str}. \
                                If no topic is selected, generate a mix of questions based on the options in {subject_to_topics} according to the subject. \
                                Display questions and their corresponding answers separately."
                        }],
                        temperature=0.5,
                        n=1,
                        frequency_penalty=0.0
                    )

                    if response.choices:
                        content = response.choices[0].message.content.strip()
                        st.session_state.generated_questions = content

                        # Display content with LaTeX rendering for both questions and answers
                        display_content_with_latex(content)

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")

    if "generated_questions" in st.session_state:
        content = st.session_state.generated_questions

        # Add a horizontal line to separate the generated output from the feedback module
        st.markdown("<hr>", unsafe_allow_html=True)

        # Add a rating and feedback section
        st.subheader("Rate the Generated Questions")

        if "feedback_submitted" not in st.session_state:
            st.session_state.feedback_submitted = False

        if st.session_state.feedback_submitted:
            st.info("You have already submitted feedback. Thank you!")
        else:
            rating = st.radio("Rate the quality of the generated questions:", [1, 2, 3, 4, 5], key="rating")
            feedback = st.text_area("Provide your feedback:", key="feedback")

            if st.button("Submit Feedback"):
                st.success("Thank you for your feedback!")
                st.session_state.feedback_submitted = True
                # Insert feedback into the database
                c.execute('INSERT INTO feedback (rating, feedback) VALUES (?, ?)', (rating, feedback))
                conn.commit()

        # Convert content to a readable format for Excel
        readable_content = convert_latex_to_text(content)
        
        # Convert content into a DataFrame for Excel export
        df = pd.DataFrame({
            "Questions": [line.strip() for line in readable_content.splitlines() if line.strip()]  # Handle splitting of content without duplications
        })

        # Convert DataFrame to Excel
        towrite = io.BytesIO()
        df.to_excel(towrite, index=False, engine='openpyxl')  # Write to BytesIO stream
        towrite.seek(0)  # Reset pointer

        # Download link
        st.download_button(label="Download Excel", data=towrite, file_name="generated_questions.xlsx", mime="application/vnd.ms-excel")

if __name__ == "__main__":
    main()
