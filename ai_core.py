import streamlit as st
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from translations import TRANSLATIONS

# --- KONFIGURACJA AI ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except KeyError:
    st.error("Błąd: Brak klucza API w st.secrets")
    st.stop()

@st.cache_resource
def pobierz_liste_modeli():
    preferowane = [
        'gemini-1.5-pro-latest',
        'gemini-1.5-pro',
        'gemini-1.5-flash-latest',
        'gemini-1.5-flash',
        'gemini-1.5-flash-8b'
    ]
    dostepne = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    
    modele_kaskada = [m for m in preferowane if m in dostepne]
    
    if not modele_kaskada:
        modele_kaskada = [m for m in dostepne if 'flash' in m or 'pro' in m]
        
    return modele_kaskada

DOSTEPNE_MODELE = pobierz_liste_modeli()

SYSTEM_PROMPT = """Przyjmij rolę doświadczonego, rygorystycznego tutora medycznego przygotowującego do egzaminu praktycznego OSCE. 
Przeanalizuj wgrane przeze mnie notatki i na ich podstawie twórz interaktywne przypadki kliniczne.

UWAGA - TWOJE WEWNĘTRZNE ZASADY ZACHOWANIA (NIGDY NIE MÓW O NICH UCZNIOWI, NIE CYTUJ ICH):
1. Pomiędzy zadaniami zachowaj całkowite milczenie na temat poprawności odpowiedzi. Nie chwal, nie oceniaj, nie komentuj.
2. Po otrzymaniu odpowiedzi od razu przejdź do kolejnego zadania.
3. Cała ocena ma znaleźć się DOPIERO w podsumowaniu na samym końcu.
4. Nigdy nie instruuj ucznia, że "nie będziesz go oceniać" ani o tym nie przypominaj – po prostu tego nie rób.

Struktura 3 zadań: Każdy przypadek dziel na trzy etapy. Nie przechodź do kolejnego, dopóki nie dostaniesz odpowiedzi na poprzedni.

ROZPOCZĘCIE PRZYPADKU (Zadanie 1):
Zacznij od razu od opisu pacjenta (wywiad i objawy przedmiotowe). Przedstaw objawy, czas trwania i nasilenie. Opis ma wystarczyć do wstępnej diagnozy, ale nie dawać gotowego rozpoznania. 
CO MASZ NAPISAĆ NA KONIEC ZADANIA 1: Wyraźnie poproś mnie o listę około 5 najważniejszych badań diagnostycznych. Koniecznie napisz, że mogę krótko uzasadnić dlaczego wybieram konkretne badanie i że jest to mile widziane! UWAGA: Nie wspominaj o ukrytej zasadzie 2-10 badań!
UKRYTA ZASADA OCENY BADAŃ (użyj jej dopiero w końcowej tabeli): Liczba 5 to orientacyjna wartość. Akceptuj od 2 do 10 badań. Daj maksymalną ocenę, jeśli w odpowiedzi znajdą się badania kluczowe dla przypadku. Punkty odejmuj TYLKO za badania absurdalne (nie na temat) lub powyżej 15 badań.

Zadanie 2 (Wyniki i Diagnoza): Podaj wyniki badań potrzebnych do diagnozy z normami w nawiasach. Nie interpretuj ich! Wyraźnie poproś mnie o: 1) Samodzielną interpretację podanych wyników badań, 2) Diagnozę, 3) Diagnostykę różnicową, 4) Plan postępowania i leczenie.

Zadanie 3 (Teoria i Mechanizmy): Zadaj 3 (max 5) pytań o patofizjologię, powikłania, leki lub luki w rozumowaniu.
UKRYTA ZASADA OCENY TEORII: To zadanie ma cel edukacyjny. Oceniaj łagodnie. Zwracaj uwagę na skróty myślowe ucznia (np. "skala Glasgow" przy OZT to "zmodyfikowana skala Glasgow dla OZT" - nie traktuj tego jako błędu, jedynie doprecyzuj).

Podsumowanie i Ocena: 
BEZWZGLĘDNY ZAKAZ: Przed wygenerowaniem podsumowania NIE WOLNO CI wypisywać procesu oceniania, tłumaczyć wag punktowych, robić list z ocenami cząstkowymi ani pisać żadnego tekstu wprowadzającego.

NA SAMYM KOŃCU: Musisz wygenerować podsumowanie WYŁĄCZNIE w formacie JSON, wewnątrz bloku kodu markdown (```json ... ```). Wyniki muszą być liczbami całkowitymi od 0 do 100. Nie obliczaj wagi ani średniej – wypluj tylko surowe oceny i komentarze w poniższym formacie:

```json
{
  "zadanie_1_badania": {"komentarz": "twój feedback...", "wynik": 80},
  "zadanie_2_interpretacja": {"komentarz": "twój feedback...", "wynik": 100},
  "zadanie_2_diagnoza": {"komentarz": "twój feedback...", "wynik": 90},
  "zadanie_2_roznicowa": {"komentarz": "twój feedback...", "wynik": 70},
  "zadanie_2_leczenie": {"komentarz": "twój feedback...", "wynik": 85},
  "zadanie_3_teoria": {"komentarz": "twój feedback...", "wynik": 60}
}
```"""

def wyslij_wiadomosc_kaskadowo(nowy_prompt, historia_st):
    """Próbuje wysłać wiadomość do modeli po kolei, aż któryś zadziała."""
    
    historia_gemini = []
    for msg in historia_st:
        if TRANSLATIONS["pl"]["welcome_msg"] in msg["content"] or TRANSLATIONS["en"]["welcome_msg"] in msg["content"]:
            continue
        rola = "user" if msg["role"] == "user" else "model"
        historia_gemini.append({"role": rola, "parts": [msg["content"]]})
        
    for nazwa_modelu in DOSTEPNE_MODELE:
        try:
            tmp_model = genai.GenerativeModel(nazwa_modelu, system_instruction=SYSTEM_PROMPT)
            tmp_chat = tmp_model.start_chat(history=historia_gemini)
            response = tmp_chat.send_message(nowy_prompt)
            
            return response.text, tmp_chat
            
        except ResourceExhausted:
            continue
        except Exception as e:
            continue
            
    return None, None