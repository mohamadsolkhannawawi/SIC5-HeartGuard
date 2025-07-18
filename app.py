import pandas as pd
import streamlit as st
import os
from dotenv import load_dotenv

from streamlit_chat import message
from streamlit_extras.let_it_rain import rain
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain.text_splitter import CharacterTextSplitter
from langchain.prompts import ChatPromptTemplate, PromptTemplate
from langchain_community.vectorstores import FAISS
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.llms import Ollama
from langchain_community.embeddings import OllamaEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_groq import ChatGroq
from dotenv import load_dotenv
import os
import random
import time
import pickle
import firebase_admin
from firebase_admin import credentials, db
from sklearn.ensemble import GradientBoostingClassifier

load_dotenv()  
groq_api_key = os.getenv("GROQ_API_KEY")
firebase_api_key = os.getenv("FIREBASE_API_KEY")

# Path ke file kunci pribadi Firebase
try:
    app = firebase_admin.get_app()
except ValueError as e:
    cred = credentials.Certificate("bpm-sic-firebase.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://bpm-sic-default-rtdb.firebaseio.com'
    })


# Load the trained model and scaler
model_filename = 'Model/best_model.sav'
scaler_filename = 'Model/scaler.sav'
loaded_model = pickle.load(open(model_filename, 'rb'))
loaded_scaler = pickle.load(open(scaler_filename, 'rb'))

def predict_heart_disease(input_data):
    # Convert input data to DataFrame
    input_df = pd.DataFrame([input_data], columns=input_data.keys())
    
    # Feature Engineering for the new input
    input_df['age_squared'] = input_df['age'] ** 2
    input_df['BMI_age_interaction'] = input_df['BMI'] * input_df['age']
    input_df['cigsPerDay_squared'] = input_df['cigsPerDay'] ** 2
    
    # Scaling the input data
    input_scaled = loaded_scaler.transform(input_df)
    
    # Predict using the loaded model
    prediction = loaded_model.predict(input_scaled)
    
    return "Risk" if prediction == 1 else "Normal"

def create_vector_db(path):
    try:
        text = []
        loader = PyPDFLoader(path)
        text.extend(loader.load())

        text_splitter = CharacterTextSplitter(separator="\n", chunk_size=1000, chunk_overlap=100, length_function=len)
        chunks = text_splitter.split_documents(text)

        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2", 
                                           model_kwargs={'device': 'cpu'})
        vector_db = FAISS.from_documents(chunks, embedding=embeddings)
        
        return vector_db
    except Exception as e:
        st.error(f"Failed to create vector store: {e}")
        return None


def process_question(query, vector_store):
    # Create llm
    llm = ChatGroq(
            groq_api_key=groq_api_key, 
            model_name='llama3-70b-8192'
    )

    QUERY_PROMPT = PromptTemplate(
        input_variables=["question"],
        template="""You are an medical AI language model assistant. Your task is to generate 3
        different versions of the given user question to retrieve relevant documents from
        a vector database. By generating multiple perspectives on the user question, your
        goal is to help the user overcome some of the limitations of the distance-based
        similarity search. Provide these alternative questions separated by newlines.
        Original question: {question}""",
    )

    retriever = MultiQueryRetriever.from_llm(
        vector_store.as_retriever(), llm, prompt=QUERY_PROMPT
    )

    template = """
        Pertanyaan user: {question}
        Jawablah pertanyaan tersebut menggunakan Bahasa Indonesia dan HANYA berdasarkan informasi berikut:
        {context}

        Jika tidak terdapat jawaban pada informasi tersebut, HANYA katakan saja:
        Saya tidak memiliki informasi dari pertanyaan yang diberikan. Untuk mengetahui informasi tersebut lebih lanjut, silahkan hubungi dokter.
        """

    prompt = ChatPromptTemplate.from_template(template)

    chain = (
        {"context": retriever, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    response = chain.invoke(query) + "\n\nApakah ada lagi yang ingin kamu tanyakan? 😁"
    return response

def initialize_session_state(vector_store, status, name):
    if 'history' not in st.session_state:
        st.session_state['history'] = []

    if 'past' not in st.session_state:
        st.session_state['past'] = ["Halo! Bagaimana keadaan jantung saya? 🤔"]

    if 'generated' not in st.session_state:
        if status == 'Risk':
            st.session_state['generated'] = [f"Halo, {name}!\n\nKamu memiliki resiko penyakit jantung koroner 😢\n\n" + process_question("Saya memiliki resiko penyakit jantung koroner, apa yang harus saya lakukan?", vector_store)]
        else:
            st.session_state['generated'] = [f"Halo, {name}!\n\nKamu memiliki jantung yang sehat 😊\n\n" + "Apakah ada yang ingin kamu ketahui mengenai penyakit jantung koroner?"]
            rain(
                emoji="🎉",
                font_size=18,
                falling_speed=5,
                animation_length=3,
            )

def conversation_chat(query, vector_store, history):
    response = process_question(query, vector_store)
    history.append((query, response))
    return response

def display_chat_history(vector_store):
    reply_container = st.container()
    container = st.container()

    with container:
        user_input = st.chat_input("Ask me something....")

        if user_input:
            with st.spinner('Generating response...'):
                output = conversation_chat(user_input, vector_store, st.session_state['history'])
                st.session_state['past'].append(user_input)
                st.session_state['generated'].append(output)

    if st.session_state['generated']:
        with reply_container:
            for i in range(len(st.session_state['generated'])):
                message(st.session_state["past"][i], is_user=True, key=str(i) + '_user', avatar_style="avataaars", seed="Aneka")
                message(st.session_state["generated"][i], key=str(i), avatar_style="bottts", seed="Aneka")


def main():
    load_dotenv()  
    groq_api_key = os.environ['GROQ_API_KEY']
    st.set_page_config(page_title="HeartGuard")
    st.title("❤️‍🩹 HeartGuard")
    st.html('<p style="text-align: justify;">An early detection of coronary heart disease Risk using IoT and chatbot system.</p>')

    st.subheader('Prediksi Resiko Penyakit Jantung Koroner 🫀')
    st.html('<p style="text-align: justify;">Penyakit jantung koroner disebut sebagai penyumbang kematian terbesar di dunia. Penyakit ini didukung oleh faktor risiko seperti kolesterol, tekanan darah tinggi, merokok, obesitas, dan diabetes. Yuk, cek risiko kamu sekarang untuk pencegahan dini dan hidup lebih sehat!</p>')
    
    st.subheader('HeartGuard Bot 🤖')

    @st.experimental_dialog("Isi Informasi Diri Kamu 👤")
    def data_diri():
        # Nama
        name = st.text_input("Nama")
        # Jenis kelamin
        sex_option = st.radio("Jenis Kelamin", ["Laki-laki", "Perempuan"], index=None, horizontal=True)
        male = 1 if sex_option == "Laki-laki" else 0
        # Umur
        age = st.number_input("Umur", 0)
        # Perokok
        perokok_option = st.radio("Apakah kamu perokok?", ["Ya", "Tidak"], index=None, horizontal=True)
        currentSmoker = 1 if perokok_option == "Ya" else 0
        cigsPerDay = st.number_input("Berapa jumlah rokok yang kamu konsumsi dalam sehari?", 0)
        # Tekanan darah
        BPmeds_option = st.radio("Apakah kamu sedang menjalani pengobatan tekanan darah?", ["Ya", "Tidak"], index=None, horizontal=True)
        BPMeds = 1 if BPmeds_option == "Ya" else 0
        # Stroke
        stroke_option = st.radio("Apakah kamu pernah mengalami stroke?", ["Ya", "Tidak"], index=None, horizontal=True)
        prevalentStroke = 1 if stroke_option == "Ya" else 0
        # Hipertensi
        hipertensi_option = st.radio("Apakah kamu pernah mengalami hipertensi?", ["Ya", "Tidak"], index=None, horizontal=True)
        prevalentHyp = 1 if hipertensi_option == "Ya" else 0
        # Diabetes
        diabetes_option = st.radio("Apakah kamu pernah mengalami diabetes?", ["Ya", "Tidak"], index=None, horizontal=True)
        diabetes = 1 if diabetes_option == "Ya" else 0
        # BMI
        berat_badan = st.number_input("Masukkan berat badan (kg)", min_value = 0.0, format="%.2f")
        tinggi_badan = st.number_input("Masukkan tinggi badan (cm)", min_value = 0.0, format="%.2f")
        
        if name and sex_option and age > 0 and perokok_option and BPmeds_option and stroke_option and hipertensi_option and diabetes_option and berat_badan > 0 and tinggi_badan > 0:
            tinggi_badan_m = tinggi_badan / 100
            BMI = round(berat_badan / (tinggi_badan_m ** 2), 1)
            if st.button("Submit"):
                st.session_state.data_diri = {"name": name, "male": male, "age": age, "currentSmoker": currentSmoker, "cigsPerDay": cigsPerDay,
                    "BPMeds": BPMeds, "prevalentStroke": prevalentStroke, "prevalentHyp": prevalentHyp, "diabetes": diabetes, "BMI":BMI}
                st.rerun()
        else:
            st.error('⚠️ Lengkapi Form Terlebih Dahulu!')
            st.button("Submit", disabled=True)

    if "data_diri" not in st.session_state:
        st.html('<p style="text-align: justify;">Untuk menggunakan aplikasi ini, silahkan isi form dibawah ini terlebih dahulu. Untuk membuka form klik tombol <strong>"Buka Form"</strong> dibawah ini.</p>')
        if st.button("Buka Form", type="primary"):
            data_diri()

    # BPM
    if "read_sensor" not in st.session_state:
        st.html('<p style="text-align: justify;">Selanjutnya, nyalakan perangkat IoT kamu terlebih dahulu dan <strong>letakkan jari kamu ke atas sensor</strong> agar sensor dapat membaca BPM dan suhu dalam tubuh kamu. Kemudian, geser toggle <strong>"Connect IoT Device"</strong> di bawah ini untuk menghubungkan perangkat IoT dengan aplikasi.</p>')
        st.warning("⚠️ Pastikan perangkat IoT sudah terhubung dengan internet!")

        on = st.toggle("Connect IoT Device")
        if on:
            ref = db.reference('Semarang')
            finger = ref.child('status').get()
            fingerStatus = finger['value']
            device = True
            if fingerStatus == 'on':
                deviceFinger = True
            else:
                deviceFinger = False
        else:
            device = False
        
        
        if device and deviceFinger:
            st.html("""<div style="text-align: center;"><strong>IoT Device Status</strong><br><span style="font-size: 28px; color: green;">Connected</span></div>""")
            st.html('<p style="text-align: justify;">Kemudian, klik tombol <strong>"Read Sensor"</strong> dibawah ini.</p>')        
            st.warning("⚠️ Pastikan kamu sudah terhubung dengan perangkat IoT sebelum menekan tombol dibawah ini!")
            if st.button("Read Sensor", type="primary") and device:
                progress_text = "Reading sensor..."
                sensor_bar = st.progress(0, text=progress_text)

                for percent_complete in range(0, 100, 10):
                    beat_avg = ref.child('beatAvg').get()
                    bpm = beat_avg['value']
                    temp = ref.child('temperature').get()
                    temperature = round(temp['value'], 1)
                    time.sleep(1)
                    sensor_bar.progress(percent_complete + 10, text=progress_text)

                time.sleep(1)
                sensor_bar.empty()

                st.session_state.read_sensor = {"bpm": bpm, "temperature": temperature}
                st.rerun()
            st.html('<p style="text-align: justify;">Setelah selesai mengisi form dan mendapatkan data dari sensor, maka akan muncul prediksi resiko jantung kamu dan chatbot jika kamu memiliki pertanyaan seputar penyakit jantung koroner.</p>')
        elif device == True and deviceFinger == False:
            st.html("""<div style="text-align: center;"><strong>IoT Device Status</strong><br><span style="font-size: 28px; color: red;">No Finger Detected</span></div>""")
        else:
            st.html("""<div style="text-align: center;"><strong>IoT Device Status</strong><br><span style="font-size: 28px; color: red;">Disconnected</span></div>""")
    
        
        

    if "data_diri" in st.session_state and "read_sensor" in st.session_state:

        st.info('Untuk mengatur ulang informasi diri anda, silahkan refresh halaman ini.')

        name = st.session_state.data_diri['name']
        BMI = st.session_state.data_diri['BMI']
        heartRate = st.session_state.read_sensor['bpm']
        temperature = st.session_state.read_sensor['temperature']

        # Collect input data
        input_data = {
            'male': st.session_state.data_diri['male'],
            'age': st.session_state.data_diri['age'],
            'currentSmoker': st.session_state.data_diri['currentSmoker'],
            'cigsPerDay': st.session_state.data_diri['cigsPerDay'],
            'BPMeds': st.session_state.data_diri['BPMeds'],
            'prevalentStroke': st.session_state.data_diri['prevalentStroke'],
            'prevalentHyp': st.session_state.data_diri['prevalentHyp'],
            'diabetes': st.session_state.data_diri['diabetes'],
            'BMI': BMI,
            'heartRate': heartRate,
        }
        
        with st.spinner('Loading chatbot...'):
            status = predict_heart_disease(input_data)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if status == 'Risk':
                st.html("""<div style="text-align: center;"><strong>Status</strong><br><span style="font-size: 28px; color: red;">Risk</span></div>""")
            else:
                st.html("""<div style="text-align: center;"><strong>Status</strong><br><span style="font-size: 28px; color: green;">Normal</span></div>""")
        with col2:
            if heartRate >= 60 and heartRate <= 100:
                st.html(f"""<div style="text-align: center;"><strong>Average BPM</strong><br><span style="font-size: 28px; color: green;">{heartRate}</span></div>""")
            else:
                st.html(f"""<div style="text-align: center;"><strong>Average BPM</strong><br><span style="font-size: 28px; color: red;">{heartRate}</span></div>""")
        with col3:
            if temperature < 35 or temperature > 38:
                st.html(f"""<div style="text-align: center;"><strong>Body Temperature</strong><br><span style="font-size: 28px; color: red;">{temperature} °C</span></div>""")
            else:
                st.html(f"""<div style="text-align: center;"><strong>Body Temperature</strong><br><span style="font-size: 28px; color: green;">{temperature} °C</span></div>""")
        with col4:
            if BMI < 18.5:
                st.html(f"""<div style="text-align: center;"><strong>BMI</strong><br><span style="font-size: 28px; color: red;">{BMI}</span></div>""")
            elif 18.5 <= BMI < 24.9:
                st.html(f"""<div style="text-align: center;"><strong>BMI</strong><br><span style="font-size: 28px; color: green;">{BMI}</span></div>""")
            elif 25 <= BMI < 29.9:
                st.html(f"""<div style="text-align: center;"><strong>BMI</strong><br><span style="font-size: 28px; color: orange;">{BMI}</span></div>""")
            else:
                st.html(f"""<div style="text-align: center;"><strong>BMI</strong><br><span style="font-size: 28px; color: red;">{BMI}</span></div>""")

        with st.spinner('Loading chatbot...'):
            # Create vector store
            vector_store = create_vector_db("Dataset/Penyakit Jantung Koroner.pdf")

            initialize_session_state(vector_store, status, name)
                
        display_chat_history(vector_store)

if __name__ == "__main__":
    main()

