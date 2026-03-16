import PyPDF2
import re
import json
import os

def konwertuj_pdf_na_json():
    sciezka_pdf = os.path.join("my_notes", "PEDSY.pdf")
    sciezka_json = os.path.join("my_notes", "PEDSY.json")
    
    if not os.path.exists(sciezka_pdf):
        print(f"BŁĄD: Nie znaleziono pliku {sciezka_pdf}! Upewnij się, że plik PEDSY.pdf tam jest.")
        return

    print("Rozpoczynam czytanie PDF... To może chwilę potrwać.")
    tekst = ""
    with open(sciezka_pdf, "rb") as plik:
        czytnik = PyPDF2.PdfReader(plik)
        for strona in czytnik.pages:
            tekst += strona.extract_text() + "\n"
            
    fragmenty = re.split(r'\[CHOROBA\]', tekst)
    lista_chorob = [f.strip() for f in fragmenty if len(f.strip()) > 50]

    with open(sciezka_json, "w", encoding="utf-8") as plik_json:
        json.dump(lista_chorob, plik_json, ensure_ascii=False, indent=4)
        
    print(f"Gotowe! Zapisano {len(lista_chorob)} chorób do pliku {sciezka_json}.")

if __name__ == "__main__":
    konwertuj_pdf_na_json()