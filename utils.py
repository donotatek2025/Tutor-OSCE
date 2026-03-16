import PyPDF2
import re
import os
import base64
from PIL import Image

# --- FUNKCJE NARZĘDZIOWE ---

def wczytaj_i_podziel_pdf(zrodlo):
    tekst = ""
    if isinstance(zrodlo, str):
        with open(zrodlo, "rb") as plik:
            czytnik = PyPDF2.PdfReader(plik)
            for strona in czytnik.pages:
                tekst += strona.extract_text() + "\n"
    else:
        czytnik = PyPDF2.PdfReader(zrodlo)
        for strona in czytnik.pages:
            tekst += strona.extract_text() + "\n"
            
    fragmenty = re.split(r'\[CHOROBA\]', tekst)
    lista_chorob = [f.strip() for f in fragmenty if len(f.strip()) > 50]
    return lista_chorob

def pobierz_awatar(rola):
    sciezka = "doctor.png" if rola == "assistant" else "point.png"
    if os.path.exists(sciezka):
        return Image.open(sciezka)
    else:
        return "🩺" if rola == "assistant" else "👤"

def pobierz_grafike_base64(sciezka):
    """Pomocnicza funkcja, która zastąpi długie linijki import("base64") w głównym pliku"""
    try:
        with open(sciezka, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return ""