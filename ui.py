# Import necessary libraries
import streamlit as st
import pandas as pd
from openai import OpenAI
import PyPDF2
import io
import openpyxl

# Apply a custom theme via Streamlit's configuration
st.set_page_config(page_title="Assessment Generator", page_icon=":pencil:", layout="wide")

# Load CSS for additional styling
with open('style.css') as f:
    st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# Set OpenAI API keys
user_api_key = st.text_input("OpenAI API Key: ", type="password")
client = OpenAI(api_key=user_api_key)

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

    # Using columns to organize inputs
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        subject_list = list(subject_to_topics.keys())
        user_input_topic = st.selectbox('Subject', subject_list)

    topics = subject_to_topics.get(user_input_topic)
    selected_topic = col2.selectbox('Topic', topics)

    with col3:
        acad_levels = ["Primary One", "Primary Two", "Primary Three", "Primary Four", "Primary Five", "Primary Six"]
        user_input_acad_level = st.selectbox('Academic Level', acad_levels)

    col4, col5, col6 = st.columns([1, 1, 3])
    with col4:
        difficulties = ["Easy", "Medium", "Hard"]
        user_input_difficulty = st.selectbox('Question Difficulty', difficulties)

    with col5:
        user_input_no_of_qns = st.number_input("Number of Questions:", min_value=1, max_value=50, value=10)
    
    with col6:
        user_input_keyword = st.text_input("Keywords (Optional): ")

    buff, col, buff2 = st.columns([1,2,1])
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
        with st.spinner('Generating questions...'):
            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[{
                        "role": "user",
                        "content": f"With reference to the content in {file_text} and {selected_topic}, generate {user_input_no_of_qns} {user_input_topic} questions with answers for the academic level of \
                            {user_input_acad_level} according to the Singapore education system in {user_input_difficulty} difficulty level. Keywords: {user_input_keyword}.\
                                Hide any annotation or irrelevant messages in the output, such as 'Sure! Here are x easy mathematics questions...'."
                    }],
                    temperature=0.5,
                    n=1,
                    frequency_penalty=0.0
                )
                if response.choices:
                    content = response.choices[0].message.content
                    st.text_area("Generated Questions", content, height=250)
                    # Convert content into a DataFrame for Excel export
                    df = pd.DataFrame({
                        "Questions": content.split('\n')  # Splitting content by new lines; adjust as needed based on actual output format
                    })
                    # Convert DataFrame to Excel
                    towrite = io.BytesIO()
                    df.to_excel(towrite, index=False, engine='openpyxl')  # Write to BytesIO stream
                    towrite.seek(0)  # Reset pointer
                    # Download link
                    st.download_button(label="Download Excel", data=towrite, file_name="generated_questions.xlsx", mime="application/vnd.ms-excel")

                    # Add a rating and feedback section
                    st.subheader("Rate the Generated Questions")
                    rating = st.slider("Rate the quality of the generated questions:", 1, 5, 3, key="rating")
                    feedback = st.text_area("Provide your feedback:", key="feedback")

                    if st.button("Submit Feedback"):
                        st.success("Thank you for your feedback!")
                        # Here you can store the feedback to a database or a file
                        # For demonstration, we will print it out
                        st.write(f"Rating: {rating}")
                        st.write(f"Feedback: {feedback}")
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()