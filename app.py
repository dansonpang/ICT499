import streamlit as st
import pandas as pd
import openai
import PyPDF2
import io
import openpyxl
import sqlite3
import re
import time
import random
from datetime import datetime, timedelta
import hashlib
import os

# Apply a custom theme via Streamlit's configuration
st.set_page_config(page_title="Assessment Generator & Grader", page_icon=":pencil:", layout="wide")

# Load CSS for additional styling
with open('style.css') as f:
    st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

# Setup SQLite database for storing feedback
conn = sqlite3.connect('feedback.db')
c = conn.cursor()

# Create or alter table to add subject and topics columns for feedback
c.execute('''
          CREATE TABLE IF NOT EXISTS feedback (
              id INTEGER PRIMARY KEY,
              question_hash TEXT UNIQUE,
              subject TEXT NOT NULL,
              topics TEXT NOT NULL,
              rating INTEGER NOT NULL,
              feedback TEXT NOT NULL,
              timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
          )
          ''')

# Create table for storing generated questions
c.execute('''
          CREATE TABLE IF NOT EXISTS generated_questions (
              id INTEGER PRIMARY KEY,
              subject TEXT NOT NULL,
              difficulty_level TEXT NOT NULL,
              question_content TEXT NOT NULL,
              generated_at DATETIME DEFAULT CURRENT_TIMESTAMP
          )
          ''')
conn.commit()

# Define cooldown period for feedback submission (in minutes)
FEEDBACK_COOLDOWN = 10

@st.cache_data
# Function to read the content from an uploaded PDF file
def read_pdf(file):
    with io.BytesIO(file.getvalue()) as f:
        reader = PyPDF2.PdfReader(f)
        text = ''.join([page.extract_text() for page in reader.pages])
    return text

# Helper function to check if user is within cooldown period for feedback submission
def within_cooldown(last_feedback_time):
    if not last_feedback_time:
        return False
    cooldown_time = last_feedback_time + timedelta(minutes=FEEDBACK_COOLDOWN)
    return datetime.now() < cooldown_time

# Generate a unique hash for the generated questions to identify feedback
def generate_question_hash(content):
    return hashlib.sha256(content.encode()).hexdigest()

# Estimate the number of tokens in the text (approximation used for API limits)
def estimate_tokens(text):
    words = text.split()
    return len(words) * 1.33  # Approximation: 1.33 words per token

# Fix repeated units in the content, such as "km/h km/h"
def fix_repeated_units(content):
    # Replace repeated occurrences of "km/h" with a single instance
    content = re.sub(r'(km/h)\s+\1', r'\1', content)
    # Replace repeated occurrences of "hours" with a single instance
    content = re.sub(r'(hours)\s+\1', r'\1', content)
    return content

# Fix unbalanced braces in the content
def fix_unbalanced_braces(content):
    # Count the number of opening and closing braces
    open_braces = content.count('{')
    close_braces = content.count('}')
    # Add missing closing braces if there are more opening braces
    if open_braces > close_braces:
        content += '}' * (open_braces - close_braces)
    # Add missing opening braces if there are more closing braces
    elif close_braces > open_braces:
        content = '{' * (close_braces - open_braces) + content
    return content

# Fix nested fractions by ensuring braces are balanced
def fix_nested_fractions(content):
    # Regular expression to match LaTeX fraction commands
    fraction_pattern = r'\\frac\{[^\}]*\}\{[^\}]*\}'
    # Apply fix_unbalanced_braces to each fraction found
    content = re.sub(fraction_pattern, lambda match: fix_unbalanced_braces(match.group()), content)
    return content

# Clean up LaTeX expressions for better formatting
def clean_latex_expression(content):
    # Remove unnecessary parentheses around fractions
    content = re.sub(r'\(\s*\\frac\{[^}]*\}\{[^}]*\}\s*\)', lambda match: match.group(0)[1:-1], content)
    # Ensure proper spacing in units like km/h and hours
    content = re.sub(r',\s*\\text{km/h}', r'\\, \text{km/h}', content)
    content = re.sub(r',\s*\\text{hours}', r'\\, \text{hours}', content)
    content = re.sub(r'\)\s*km/h', r'\\, \text{km/h})', content)
    content = re.sub(r'\)\s*hours', r'\\, \text{hours})', content)
    # Fix fraction formatting by ensuring no extra spaces
    content = re.sub(r'\\frac\s*\{(.*?)\}\s*\{(.*?)\}', r'\\frac{\1}{\2}', content)
    # Remove repeated units like "km/h km/h" or "hours hours"
    content = re.sub(r'(km/h)\s+(km/h)', r'\1', content)
    content = re.sub(r'(hours)\s+(hours)', r'\1', content)
    return content

# Apply a series of fixes to LaTeX expressions to improve formatting
def fix_latex_expressions(content):
    # Fix unbalanced braces first
    content = fix_unbalanced_braces(content)
    # Fix repeated units
    content = fix_repeated_units(content)
    # Remove extra spaces inside parentheses
    content = re.sub(r'\(\s+', '(', content)
    content = re.sub(r'\s+\)', ')', content)
    # Clean up LaTeX expressions for better formatting
    content = clean_latex_expression(content)
    return content

# Ensure that LaTeX expressions are complete, particularly fractions and text commands
def complete_latex_expressions(content):
    # Fix nested fractions by balancing braces
    content = fix_nested_fractions(content)
    # Ensure fractions are complete if braces are missing
    content = re.sub(r'\\frac\{([^\}]*)$', r'\\frac{\1}', content)
    # Ensure text commands are complete if braces are missing
    content = re.sub(r'\\text\{([^\}]*)$', r'\\text{\1}', content)
    return content

# Custom LaTeX processing function that combines multiple fixes
def custom_latex_processing(content):
    # Fix unbalanced braces
    content = fix_unbalanced_braces(content)
    # Complete LaTeX expressions for fractions and text commands
    content = complete_latex_expressions(content)
    # Fix repeated units in the content
    content = fix_repeated_units(content)
    return content

# Display LaTeX content with proper formatting in Streamlit
def display_content_with_latex(content):
    # Apply custom LaTeX processing to clean up the content
    content = custom_latex_processing(content)
    # Define patterns for LaTeX expressions to identify them
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
        r'\\begin\{align\*?\}.*?\\end\{align\*?\}',  # Align and align* environments
    ]
    latex_regex = re.compile('|'.join(latex_patterns))
    # Split content based on LaTeX patterns
    parts = re.split(
        r'('  # Start a capturing group
        r'\$.*?\$|'  # Inline math
        r'\\frac\{.*?\}\{.*?\}|'  # Fractions
        r'\\sqrt(?:\{.*?\})?|'  # Square root
        r'\\sum(?:_\{.*?\})?(?:\^\{.*?\})?|'  # Summation
        r'\\int(?:_\{.*?\})?(?:\^\{.*?\})?|'  # Integral
        r'\^\{.*?\}|'  # Exponents (Superscripts)
        r'_\{.*?\}|'  # Subscripts
        r'\\begin\{.*?matrix\}.*?\\end\{.*?matrix\}|'  # Matrices and arrays
        r'\\text\{.*?\}|'  # Text formatting in math mode
        r'\\[a-zA-Z]+(?=\W|\Z)|'  # Greek letters
        r'\\(?:log|sin|cos|tan|ln|exp|arcsin|arccos|arctan)\b|'  # Trig and log functions
        r'\\left[\(\[\{].*?\\right[\)\]\}]|'  # Parentheses and Brackets
        r'\\begin\{aligned\}.*?\\end\{aligned\}'  # Aligned equations
        r')', 
        content
)
    # Process each part to format LaTeX content
    processed_parts = []
    for part in parts:
        if latex_regex.search(part):
            processed_parts.append(f"$$ {part.strip()} $$")
        else:
            processed_parts.append(part.strip())
    final_content = ' '.join(processed_parts)
    # Display the processed content in Streamlit
    st.markdown(final_content)

# Convert LaTeX to plain text for display or export
def convert_latex_to_text(content):
    content = re.sub(r'\\frac\{(.*?)\}\{(.*?)\}', r'\1/\2', content)
    content = re.sub(r'\\text\{(.*?)\}', r'\1', content)
    return content

def main():
    # Initialize session state
    if 'generated_questions' not in st.session_state:
        st.session_state.generated_questions = ""
    if 'feedback_submitted' not in st.session_state:
        st.session_state.feedback_submitted = False
    if 'last_feedback_time' not in st.session_state:
        st.session_state.last_feedback_time = None
    if 'question_hash' not in st.session_state:
        st.session_state.question_hash = None

    st.title("Assessment Generator & Grader")
    st.subheader("Generate Assessments based on Academic Level, Topics, and Language or Grade them")

    with st.form(key="api_form"):
        user_api_key = st.text_input("OpenAI API Key:", type="password")
        submit_button = st.form_submit_button(label="Set API Key")

    if submit_button:
        st.session_state.api_key = user_api_key
        st.success("API key set successfully!")

    # Ensure API key is never directly visible in Streamlit widgets or logs
    if not st.session_state.get('api_key'):
        st.warning("Please enter and confirm your OpenAI API key to continue.")
        st.stop()

    # Configure OpenAI client using API key securely
    openai.api_key = st.session_state.api_key

    # Create tabs for Teachers (Assessment Generation), Students (Grading), and Guide
    tab1, tab2, tab3 = st.tabs(["Assessment Generation", "Grade Assessments", "Guide"])

    # Mapping subjects to topics
    subject_to_topics = {
        "Mathematics": ["Whole Numbers", "Algebra", "Money", "Measurement and Geometry", "Statistics", "Fractions", "Time", "Area and Volume", "Decimals", "Multiplication and Division", "Percentage", "Ratio", "Rate and Speed"],
        "English Language": ["Grammar", "Literature", "Writing", "Reading Comprehension"],
        "Science": ["Physics", "Chemistry", "Biology"],
        "Social Studies": ["Discovering Self and Immediate Environment", "Understanding Singapore in the Past and Present", "Appreciating Singapore, the Region and the World We Live In"]
    }

    with tab1:
        st.subheader("Generate Assessments based on Academic Level, Topics, and Language")

        # Language selection
        language_options = {
            "English": "en",
            "Spanish": "es",
            "French": "fr",
            "Chinese": "zh",
            "German": "de",
            "Japanese": "ja"
        }
        language = st.selectbox("Choose a Language", list(language_options.keys()))

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
            # Adding a tooltip for the "Keywords" field
            user_input_keyword = st.text_input("Keywords (Optional):", help="Use specific keywords to guide the type of questions generated. For example, 'fractions' for math, or 'grammar' for English.")

        specify_portions = st.checkbox("Specify Topic Portioning for Assessment?")
        portions_info = {}

        if specify_portions:
            if len(selected_topics) > 1:
                st.markdown("### Enter the portion of the assessment (in %) to be allocated to each topic:")
                total_weight = 0
                for topic in selected_topics:
                    weight = st.number_input(f"Portion for {topic} (%)", min_value=0, max_value=100, value=0)
                    portions_info[topic] = weight
                    total_weight += weight

                if total_weight != 100:
                    st.error("The total portioning must sum up to 100%. Please adjust your inputs.")
            else:
                st.warning("Portioning is only available when multiple topics are selected.")

        st.info("Upload text or PDF files with content you want to use as reference(s).")

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
            if token_count > 100000:
                st.error(f"The combined document is too long ({int(token_count)} tokens). Please reduce the file content (Max tokens = 100000).")
            else:
                st.text_area("File content", file_text, height=250)

        if st.button("Generate Questions"):
            if specify_portions and sum(portions_info.values()) != 100:
                st.error("Please ensure the total portions sums up to 100% before generating questions.")
            else:
                with st.spinner('Generating questions...'):
                    progress = st.progress(0)
                    i = 0

                    try:
                        selected_topics_str = "Any" if "Any" in selected_topics else ", ".join(selected_topics)
                        portions_str = ', '.join([f"{topic}: {weight}%" for topic, weight in portions_info.items()]) if specify_portions else "Not specified"

                        if question_type == "Comprehensive Exam-Style Questions":
