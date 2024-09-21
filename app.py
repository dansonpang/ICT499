import streamlit as st
import pandas as pd
import openai
import PyPDF2
import io
import openpyxl
import sqlite3
import re
import time

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
    with io.BytesIO(file.getvalue()) as f:
        reader = PyPDF2.PdfReader(f)
        text = ''.join([page.extract_text() for page in reader.pages])
    return text

def estimate_tokens(text):
    words = text.split()
    return len(words) * 1.33  # Approximation: 1.33 words per token

def fix_repeated_units(content):
    content = re.sub(r'(km/h)\s+\1', r'\1', content)
    content = re.sub(r'(hours)\s+\1', r'\1', content)
    return content

def fix_unbalanced_braces(content):
    open_braces = content.count('{')
    close_braces = content.count('}')
    if open_braces > close_braces:
        content += '}' * (open_braces - close_braces)
    elif close_braces > open_braces:
        content = '{' * (close_braces - open_braces) + content
    return content

def fix_nested_fractions(content):
    fraction_pattern = r'\\frac\{[^\}]*\}\{[^\}]*\}'
    content = re.sub(fraction_pattern, lambda match: fix_unbalanced_braces(match.group()), content)
    return content

def clean_latex_expression(content):
    content = re.sub(r'\(\s*\\frac\{[^}]*\}\{[^}]*\}\s*\)', lambda match: match.group(0)[1:-1], content)
    content = re.sub(r',\s*\\text{km/h}', r'\\, \text{km/h}', content)
    content = re.sub(r',\s*\\text{hours}', r'\\, \text{hours}', content)
    content = re.sub(r'\)\s*km/h', r'\\, \text{km/h})', content)
    content = re.sub(r'\)\s*hours', r'\\, \text{hours})', content)
    content = re.sub(r'\\frac\s*\{(.*?)\}\s*\{(.*?)\}', r'\\frac{\1}{\2}', content)
    content = re.sub(r'(km/h)\s+(km/h)', r'\1', content)
    content = re.sub(r'(hours)\s+(hours)', r'\1', content)
    return content

def fix_latex_expressions(content):
    content = fix_unbalanced_braces(content)
    content = fix_repeated_units(content)
    content = re.sub(r'\(\s+', '(', content)
    content = re.sub(r'\s+\)', ')', content)
    content = clean_latex_expression(content)
    return content

def complete_latex_expressions(content):
    content = fix_nested_fractions(content)
    content = re.sub(r'\\frac\{([^\}]*)$', r'\\frac{\1}', content)
    content = re.sub(r'\\text\{([^\}]*)$', r'\\text{\1}', content)
    return content

def custom_latex_processing(content):
    content = fix_unbalanced_braces(content)
    content = complete_latex_expressions(content)
    content = fix_repeated_units(content)
    return content

def display_content_with_latex(content):
    content = custom_latex_processing(content)
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
    ]
    latex_regex = re.compile('|'.join(latex_patterns))
    parts = re.split(r'(\$.*?\$|\\frac\{.*?\}\{.*?\}|\\sqrt(?:\{.*?\})?|\\sum(?:_\{.*?\})?(?:\^\{.*?\})?|\\int(?:_\{.*?\})?(?:\^\{.*?\})?|\^\{.*?\}|_\{.*?\}|\\begin\{.*?matrix\}.*?\\end\{.*?matrix\}|\\text\{.*?\}|\\[a-zA-Z]+(?=\W|\Z)|\\(?:log|sin|cos|tan|ln|exp|arcsin|arccos|arctan)\b|\\left[\(\[\{].*?\\right[\)\]\}]|\\begin\{aligned\}.*?\\end\{aligned\})', content)
    processed_parts = []
    for part in parts:
        if latex_regex.search(part):
            processed_parts.append(f"$$ {part.strip()} $$")
        else:
            processed_parts.append(part.strip())
    final_content = ' '.join(processed_parts)
    st.markdown(final_content)

def convert_latex_to_text(content):
    content = re.sub(r'\\frac\{(.*?)\}\{(.*?)\}', r'\1/\2', content)
    content = re.sub(r'\\text\{(.*?)\}', r'\1', content)
    return content

# Mapping subjects to topics
subject_to_topics = {
    "Mathematics": ["Whole Numbers", "Algebra", "Money", "Measurement and Geometry", "Statistics", "Fractions", "Time", "Area and Volume", "Decimals", "Multiplication and Division", "Percentage", "Ratio", "Rate and Speed"],
    "English Language": ["Grammar", "Literature", "Writing", "Reading Comprehension"],
    "Science": ["Physics", "Chemistry", "Biology"],
    "Social Studies": ["Discovering Self and Immediate Environment", "Understanding Singapore in the Past and Present", "Appreciating Singapore, the Region and the World We Live In"]
}

# Language options for the application
language_options = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "Chinese": "zh",
    "German": "de",
    "Japanese": "ja"
}

def main():
    if 'generated_questions' not in st.session_state:
        st.session_state.generated_questions = ""
    if 'feedback_submitted' not in st.session_state:
        st.session_state.feedback_submitted = False

    st.title("Assessment Generator")
    st.subheader("Generate Assessments based on Academic Level, Topics, and Language")

    # Language selection
    language = st.selectbox("Choose a Language", list(language_options.keys()))

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
        question_type = st.selectbox("Question Type", ["Short Questions", "Comprehensive Exam-Style Questions"])

    with col6:
        user_input_no_of_qns = st.number_input("Number of Questions:", min_value=1, max_value=50, value=10)
    
    with col6:
        user_input_keyword = st.text_input("Keywords (Optional): ")

    specify_weightage = st.checkbox("Specify weightage of topics?")
    weightage_info = {}

    if specify_weightage:
        if len(selected_topics) > 1:
            st.markdown("### Enter the weightage for each selected topic:")
            total_weight = 0
            for topic in selected_topics:
                weight = st.number_input(f"Weightage for {topic} (%)", min_value=0, max_value=100, value=0)
                weightage_info[topic] = weight
                total_weight += weight
            if total_weight != 100:
                st.error("Total weightage must sum up to 100%. Please adjust your inputs.")
        else:
            st.warning("Weightage is only available when multiple topics are selected.")

    buff, col, buff2 = st.columns([1, 2, 1])
    with col:
        uploaded_files = st.file_uploader("Upload files (PDFs or Text)", type=['txt', 'pdf'], accept_multiple_files=True)

    file_text = ""
    if uploaded_files:
        combined_texts = []
        for uploaded_file in uploaded_files:
            if uploaded_file.type == "text/plain":
                combined_texts.append(str(uploaded_file.read(), "utf-8"))
            elif uploaded_file.type == "application/pdf":
                combined_texts.append(read_pdf(uploaded_file))

        file_text = "\n".join(combined_texts)
        st.success(f"{len(uploaded_files)} files uploaded successfully!")
        token_count = estimate_tokens(file_text)
        if token_count > 3000:
            st.error(f"The combined document is too long ({int(token_count)} tokens). Please reduce the file content (Max tokens = 3000).")
        else:
            st.text_area("File content", file_text, height=250)

    if st.button("Generate Questions"):
        if specify_weightage and sum(weightage_info.values()) != 100:
            st.error("Please ensure the total weightage sums up to 100% before generating questions.")
        else:
            with st.spinner('Generating questions...'):
                progress = st.progress(0)
                try:
                    selected_topics_str = "Any" if "Any" in selected_topics else ", ".join(selected_topics)
                    weightage_str = ', '.join([f"{topic}: {weight}%" for topic, weight in weightage_info.items()]) if specify_weightage else "Not specified"

                    if question_type == "Comprehensive Exam-Style Questions":
                        prompt_type = f"generate {user_input_no_of_qns} {user_input_topic} long, multi-part questions suitable for exams that carry more marks and require detailed answers"
                    else:
                        prompt_type = f"generate {user_input_no_of_qns} {user_input_topic} short quiz questions"

                    for percent_complete in range(0, 101, 10):
                        time.sleep(0.1)
                        progress.progress(percent_complete)

                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{
                            "role": "user",
                            "content": f"You are a primary school teacher in Singapore. With reference to the content in {file_text}, if any, \
                                and topics {selected_topics_str}, {prompt_type} with corresponding answers for the academic level of \
                                {user_input_acad_level} according to the Singapore education system of {user_input_difficulty} difficulty level. \
                                Please generate the content in {language_options[language]}. Keywords: {user_input_keyword}. \
                                Display only questions and answers without caption or commentary. \
                                Use LaTeX for rendering fractions and algebraic expressions. Present these questions and answers in a format that is clear and readable to users. \
                                Weightage information: {weightage_str}. \
                                If no topic is selected, generate a mix of questions based on the options in {subject_to_topics} according to the subject. \
                                Display questions and their corresponding answers separately, and ensure that all mathematical expressions can be processed through LaTeX."
                        }],
                        temperature=0.5,
                        n=1,
                        frequency_penalty=0.0
                    )

                    if response.choices:
                        st.session_state.generated_questions = response.choices[0].message.content.strip()
                        display_content_with_latex(st.session_state.generated_questions)

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")

    if st.session_state.generated_questions:
        st.subheader("Rate the Generated Questions")

        with st.form(key="feedback_form"):
            rating = st.radio("Rate the quality of the generated questions:", [1, 2, 3, 4, 5], key="rating")
            feedback = st.text_area("Provide your feedback:", key="feedback")

            if st.form_submit_button("Submit Feedback"):
                st.success("Thank you for your feedback!")
                c.execute('INSERT INTO feedback (rating, feedback) VALUES (?, ?)', (rating, feedback))
                conn.commit()

        readable_content = convert_latex_to_text(st.session_state.generated_questions)
        df = pd.DataFrame({"Questions": [line.strip() for line in readable_content.splitlines() if line.strip()]})
        towrite = io.BytesIO()
        df.to_excel(towrite, index=False, engine='openpyxl')
        towrite.seek(0)

        st.download_button(label="Download Excel", data=towrite, file_name="generated_questions.xlsx", mime="application/vnd.ms-excel")

    # Disclaimer
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("""
    **Disclaimer:** This tool is intended for reference purposes only and should not be used as an official source of educational material. 
    The generated content may not always be accurate or reflect current educational standards. Users are encouraged to review and verify 
    the material independently.
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
