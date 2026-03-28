import streamlit as st
from PIL import Image
import PyPDF2
import os
import google.generativeai as genai
import re
import random
from google.api_core.exceptions import ResourceExhausted
from datetime import datetime
import markdown
import json
import sqlite3
import pandas as pd
import hashlib
import altair as alt
from translations import TRANSLATIONS
from database import register_user, login_user, update_password, save_result_to_db, login_user, register_user, update_password, get_user_info, update_user_email, update_user_language, delete_user_account
from ai_core import wyslij_wiadomosc_kaskadowo
from utils import wczytaj_i_podziel_pdf, pobierz_awatar, pobierz_grafike_base64
from streamlit_cookies_controller import CookieController
controller = CookieController()

ICONS_PATH = "ikony"

# JĘZYK
def t(key):
    lang = st.session_state.get('lang', 'pl')
    return TRANSLATIONS.get(lang, TRANSLATIONS['pl']).get(key, key)


# KONFIGURACJA STRONY I WYGLĄDU
st.set_page_config(
    page_title="Tutor OSCE", 
    page_icon=os.path.join(ICONS_PATH, "stethoscope.png"), 
    layout="wide"
)

logo_path = os.path.join(ICONS_PATH, "stethoscope.png")
logo_base64 = __import__("base64").b64encode(open(logo_path, "rb").read()).decode()

st.markdown(
    f"""
    <div style="text-align: center; margin-bottom: 20px; padding: 20px 0;">
        <div style="display: flex; justify-content: center; align-items: center; gap: 20px; margin-bottom: 10px;">
            <img src="data:image/png;base64,{logo_base64}" width="65">
            <h1 style="margin: 0; font-size: 2.5rem; color: #1B211A; font-weight: 800; letter-spacing: -1px;">
                {t('title')}
            </h1>
        </div>
        <hr style="border: 0; height: 2px; background: linear-gradient(to right, transparent, #84B179, transparent); margin-top: 25px; opacity: 0.5;">
    </div>
    """,
    unsafe_allow_html=True
)
with open("style.css", "r", encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

def pobierz_awatar(rola):
    sciezka = "ikony/doctor.png" if rola == "assistant" else "ikony/point.png"
    if os.path.exists(sciezka):
        return Image.open(sciezka)
    else:
        return "🩺" if rola == "assistant" else "👤"
    
# FUNKCJE NARZĘDZIOWE

@st.cache_data

def pokaz_powiadomienie(tekst, ikona="✅"):
    st.markdown(
        f"""
        <div style="background-color: #EAF4EA; border-left: 5px solid #84B179; padding: 12px; border-radius: 4px; color: #1B211A; font-size: 14px; margin-bottom: 10px;">
            {ikona} {tekst}
        </div>
        """, 
        unsafe_allow_html=True
    )

def generuj_raport_html(wszystkie_przypadki):
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: auto; padding: 20px; }}
            h1 {{ color: #2c3e50; border-bottom: 2px solid #2c3e50; }}
            h2 {{ color: #e67e22; margin-top: 30px; border-bottom: 1px solid #eee; }}
            .przypadek {{ background: #f9f9f9; padding: 15px; border-radius: 8px; margin-bottom: 40px; border-left: 5px solid #2c3e50; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background: white; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .wynik {{ font-weight: bold; font-size: 1.2em; color: #27ae60; }}
            .sekcja-tytul {{ font-weight: bold; color: #7f8c8d; text-transform: uppercase; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <h1>{t('report_title')}</h1>
        <p>{t('report_date')} {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
    """ 
    for i, p in enumerate(wszystkie_przypadki):
        html += f"<div class='przypadek'><h2>{t('report_case')} {i+1} - {t('report_score')} {p['wynik']}%</h2>"
        opis = p['historia'][0]['content'] if len(p['historia']) > 0 else ""
        podsumowanie = p['historia'][-1]['content'] if "OSTATECZNY WYNIK" in p['historia'][-1]['content'] or "FINAL SCORE" in p['historia'][-1]['content'] else t('report_no_summary')
        html += f"<div class='sekcja-tytul'>{t('report_desc')}</div>"
        html += f"<div>{markdown.markdown(opis)}</div>"
        html += f"<div class='sekcja-tytul'>{t('report_eval')}</div>"
        html += f"<div>{markdown.markdown(podsumowanie)}</div>"
        html += "</div><hr>"
    html += "</body></html>"
    return html

# INICJALIZACJA PAMIĘCI

if "lang" not in st.session_state:
    st.session_state.lang = "pl"

if "logged_in" not in st.session_state:
    zapisany_user = controller.get("tutor_osce_user")
    
    if zapisany_user:
        st.session_state.logged_in = True
        st.session_state.user_nick = zapisany_user
        
        try:
            user_info = get_user_info(zapisany_user)
            db_lang = user_info.get("language", "pl")
            if db_lang == "Polski": db_lang = "pl"
            if db_lang == "English": db_lang = "en"
            st.session_state.lang = db_lang
        except Exception:
            pass 
    else:
        st.session_state.logged_in = False

if "show_register" not in st.session_state:
    st.session_state.show_register = False

if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": t("welcome_msg")}]

if "historia_wynikow" not in st.session_state:
    st.session_state.historia_wynikow = []

if "zapisane_przypadki" not in st.session_state:
    st.session_state.zapisane_przypadki = []

if "widok_archiwum" not in st.session_state:
    st.session_state.widok_archiwum = None

if "liczba_podpowiedzi" not in st.session_state:
    st.session_state.liczba_podpowiedzi = 0


# SIDEBAR
with st.sidebar:
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 10px;">
            <div style="display: flex; justify-content: center;">
                <img src="data:image/png;base64,{}" width="60">
            </div>
            <hr style="border: 0; height: 2px; background: linear-gradient(to right, transparent, #84B179, transparent); margin-top: 20px; opacity: 0.5;">
        </div>
        """.format(
            __import__("base64").b64encode(open("ikony/medical-report.png", "rb").read()).decode()
        ),
        unsafe_allow_html=True
    )
    


    # Bazy
    medical_book_base64 = __import__("base64").b64encode(open("ikony/medical-book.png", "rb").read()).decode()
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">
            <img src="data:image/png;base64,{medical_book_base64}" width="30">
            <h3 style="margin: 0; color: #1B211A;">{t("knowledge_base")}</h3>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    with st.expander(t("open_files"), expanded=False):
        lista_wszystkich_chorob = []
        
    
        dostepne_pliki = []
        if os.path.exists("my_notes"):
            dostepne_pliki = [f for f in os.listdir("my_notes") if f.endswith(".json")]
            
        if not dostepne_pliki:
            st.markdown(
                """
                <div style="background-color: #F5F0E6; border-left: 5px solid #84B179; padding: 12px; border-radius: 4px; color: #1B211A; font-size: 14px;">
                    {t('no_json')}
                </div>
                """, 
                unsafe_allow_html=True
            )
        else:
            st.markdown(f"<div style='margin-bottom: 10px; font-weight: normal; color: #1B211A;'>{t('select_bases')}</div>", unsafe_allow_html=True)
            
        
            for nazwa_pliku in dostepne_pliki:
                sciezka_json = os.path.join("my_notes", nazwa_pliku)
                
                try:
                    with open(sciezka_json, "r", encoding="utf-8") as f:
                        choroby_domyslne = json.load(f)
                except json.JSONDecodeError:
                    st.error(f"❌ {t('error')}: {nazwa_pliku}")
                    continue 
                except Exception as e:
                    st.error(f"❌ {t('error')}: {nazwa_pliku}: {e}")
                    continue
            

                kategoria_pliku = nazwa_pliku.replace(".json", "").lower()
                nazwa_wyswietlana = nazwa_pliku.replace(".json", "")
                ile_przypadkow = len(choroby_domyslne)
                
            
                czy_aktywna = st.toggle(
                    f" **{nazwa_wyswietlana}** ({ile_przypadkow} {t('cases_count')})",
                    value=True, 
                    key=f"toggle_{nazwa_pliku}"
                )
                
            
                if czy_aktywna:

                    for opis_choroby in choroby_domyslne:
                        lista_wszystkich_chorob.append({
                            "opis": opis_choroby,
                            "kategoria": kategoria_pliku
                        })

        st.divider()

    
        wgrany_plik = st.file_uploader(t("upload_pdf"), type=["pdf"], key="pdf_uploader_baza")
        
        if wgrany_plik is not None:
            choroby_dodatkowe = wczytaj_i_podziel_pdf(wgrany_plik)

            for opis_choroby in choroby_dodatkowe:
                lista_wszystkich_chorob.append({
                    "opis": opis_choroby,
                    "kategoria": "wlasne"
                })

            st.markdown(
                f"""
                <div style="background-color: #EAF4EA; border-left: 4px solid #088C6F; padding: 10px; margin-top: 10px; border-radius: 4px; color: #088C6F;">
                    📄 <b>{t("your_pdf")}</b>: {len(choroby_dodatkowe)} przypadków
                </div>
                """, unsafe_allow_html=True
            )

    st.divider()


# losowanie przypadków

    pills_base64 = __import__("base64").b64encode(open("ikony/pills.png", "rb").read()).decode()
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px;">
            <img src="data:image/png;base64,{pills_base64}" width="30">
            <h3 style="margin: 0; color: #1B211A;">{t("new_case")}</h3>
        </div>
        """, 
        unsafe_allow_html=True
    )
    if st.button(t("draw_patient"), use_container_width=True, disabled=len(lista_wszystkich_chorob) == 0):
        with st.spinner(t("spinner_analyzing")):
            st.session_state.messages = []
            st.session_state.widok_archiwum = None
            st.session_state.liczba_podpowiedzi = 0
            
           
            wylosowany_element = random.choice(lista_wszystkich_chorob)
            wylosowana_choroba = wylosowany_element["opis"]
            wylosowana_kategoria = wylosowany_element["kategoria"]
            
        
            st.session_state.aktywna_kategoria = wylosowana_kategoria
            
            
            st.toast(t("toast_category").format(wylosowana_kategoria), icon="🎯")

            if st.session_state.lang == "pl":
                prompt_startowy = f"Prowadź całą symulację, odpowiadaj, oceniaj i zadawaj pytania WYŁĄCZNIE w języku polskim.\n\nOto opis wylosowanej jednostki chorobowej z moich notatek:\n\n{wylosowana_choroba}\n\nPrzeanalizuj ją po cichu i od razu rozpocznij ze mną Zadanie 1 (Opis pacjenta)."
            else:
                prompt_startowy = f"Conduct the entire simulation, respond, evaluate, and ask questions EXCLUSIVELY in English.\n\nHere is the description of the drawn disease from my notes:\n\n{wylosowana_choroba}\n\nAnalyze it silently and immediately start Task 1 (Patient description) with me."
            
            odpowiedz_tekst, nowa_sesja = wyslij_wiadomosc_kaskadowo(prompt_startowy, [])
            
            if odpowiedz_tekst:
                st.session_state.chat_session = nowa_sesja
                st.session_state.messages.append({"role": "assistant", "content": odpowiedz_tekst})
                st.rerun()
            else:
                st.error(t("err_models_busy"))

        st.divider()

    users_base64 = __import__("base64").b64encode(open("ikony/users.png", "rb").read()).decode()
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px;">
            <img src="data:image/png;base64,{users_base64}" width="30">
            <h3 style="margin: 0; color: #1B211A;">Status</h3>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    if st.session_state.logged_in:
        st.markdown(
        f"""
        <div style="background-color: #EAF4EA; border-left: 5px solid #84B179; padding: 12px; border-radius: 4px; color: #1B211A; font-size: 14px; margin-bottom: 10px;">
           {t("logged_in_as")} <span style="color: #088C6F; font-weight: bold;">{st.session_state.user_nick}</span>
        </div>
        """, 
        unsafe_allow_html=True
        )
    else:
        st.markdown(
        f"""
        <div style="background-color: #EAF4EA; border-left: 5px solid #84B179; padding: 12px; border-radius: 4px; color: #1B211A; font-size: 14px; margin-bottom: 10px;">
            {t('login_prompt')}
        </div>
        """, 
        unsafe_allow_html=True
        )
        
    st.divider()

  # Wybór języka
    
    try:
        pl_img = __import__("base64").b64encode(open("ikony/poland.png", "rb").read()).decode()
        en_img = __import__("base64").b64encode(open("ikony/british.png", "rb").read()).decode()
    
    except FileNotFoundError:
        st.error(f"{t('error')} : poland.png / british.png")
        pl_img, en_img = "", ""


    pl_style = "filter: none;" if st.session_state.lang == "pl" else "filter: grayscale(100%) opacity(40%);"
    en_style = "filter: none;" if st.session_state.lang == "en" else "filter: grayscale(100%) opacity(40%);"


    pl_tab_style = "background-color: #84B179; border: 2px solid #84B179; border-radius: 8px 8px 0px 0px; padding: 12px;" if st.session_state.lang == "pl" else "background-color: #F5F0E6; border: 0px solid transparent; border-radius: 8px 8px 0px 0px; padding: 12px;"
    en_tab_style = "background-color: #84B179; border: 2px solid #84B179; border-radius: 8px 8px 0px 0px; padding: 12px;" if st.session_state.lang == "en" else "background-color: #F5F0E6; border: 0px solid transparent; border-radius: 8px 8px 0px 0px; padding: 12px;"

    col_pl, col_en = st.columns(2)

    with col_pl:
        if pl_img:
    
            st.markdown(f'<div style="text-align: center; margin-bottom: -15px;"><div style="display: inline-block; {pl_tab_style}"><img src="data:image/png;base64,{pl_img}" width="45" style="{pl_style} border-radius: 4px; transition: 0.3s; display: block;"></div></div>', unsafe_allow_html=True)
        
        if st.button("Polski", use_container_width=True):
            if st.session_state.lang != "pl":
                st.session_state.lang = "pl"
                st.session_state.messages = [{"role": "assistant", "content": TRANSLATIONS["pl"]["welcome_msg"]}]
                st.session_state.chat_session = None
                st.session_state.liczba_podpowiedzi = 0
                st.session_state.widok_archiwum = None
                st.rerun()

    with col_en:
        if en_img:
    
            st.markdown(f'<div style="text-align: center; margin-bottom: -15px;"><div style="display: inline-block; {en_tab_style}"><img src="data:image/png;base64,{en_img}" width="45" style="{en_style} border-radius: 4px; transition: 0.3s; display: block;"></div></div>', unsafe_allow_html=True)
        
        if st.button("English", use_container_width=True):
            if st.session_state.lang != "en":
                st.session_state.lang = "en"
                st.session_state.messages = [{"role": "assistant", "content": TRANSLATIONS["en"]["welcome_msg"]}]
                st.session_state.chat_session = None
                st.session_state.liczba_podpowiedzi = 0
                st.session_state.widok_archiwum = None
                st.rerun()

    st.divider()

    st.markdown(
        f"""
        <div style="font-size: 10px; color: #7f8c8d; line-height: 1.2; text-align: center;">
            {t('ikona')}
            <a href="https://www.flaticon.com/authors/smashingstocks" 
               title="smashingstocks" 
               style="color: #088C6F; text-decoration: none; font-weight: bold;">
               smashingstocks
            </a> 
            z platformy <a href="https://www.flaticon.com/" style="color: grey;">Flaticon</a>
        </div>
        """, 
        unsafe_allow_html=True
    )

# GŁÓWNY CZAT / ARCHIWUM

tab_symulacja, tab_konto, tab_statystyki = st.tabs([t("tab_sim"), t("tab_login"), t("tab_stats")])

with tab_symulacja:
    
    def renderuj_wiadomosc(wiadomosc):
        tresc = wiadomosc["content"]
        ekg_match = re.search(r"\[WYŚWIETL_EKG:\s*(.*?)\]", tresc)
        
        if ekg_match:
            nazwa_obrazka = ekg_match.group(1).strip()
            czysty_tekst = tresc.replace(ekg_match.group(0), "").strip()
            
            if czysty_tekst:
                st.markdown(czysty_tekst)
                
            sciezka_ekg = os.path.join("ikony", nazwa_obrazka)
            if os.path.exists(sciezka_ekg):
                st.image(sciezka_ekg, caption="Zapis EKG / Badanie Obrazowe", use_container_width=True)
            else:
                st.error(f"⚠️ {t('error')}: Brak pliku obrazkowego -> {sciezka_ekg}")
        else:
            st.markdown(tresc)

    # --- WYŚWIETLANIE ARCHIWUM LUB CZATU ---
    if st.session_state.widok_archiwum is not None:
        i = st.session_state.widok_archiwum
        przypadek = st.session_state.zapisane_przypadki[i]
        
        st.subheader(f"{t('archive_case')} {i+1} ({t('report_score')} {przypadek['wynik']}%)")
        if st.button(t("back_to_current")):
            st.session_state.widok_archiwum = None
            st.rerun()
            
        st.divider()
        for message in przypadek['historia']:
            with st.chat_message(message["role"], avatar=pobierz_awatar(message["role"])):
                renderuj_wiadomosc(message)
                
    else:
        for message in st.session_state.messages:
            with st.chat_message(message["role"], avatar=pobierz_awatar(message["role"])):
                renderuj_wiadomosc(message)

    # POLE TEKSTOWE
        czy_mozna_pisac = False
        
        if st.session_state.chat_session is not None:
            if len(st.session_state.messages) > 0:
                ostatni_tekst = st.session_state.messages[-1]["content"]
                if "OSTATECZNY WYNIK" not in ostatni_tekst:
                    czy_mozna_pisac = True

        if czy_mozna_pisac:
            
            ile_podpowiedzi = st.session_state.liczba_podpowiedzi
            
            
            col_pusta, col_przycisk = st.columns([4, 1])
            
            with col_przycisk:
                if ile_podpowiedzi < 3:
                    tekst_przycisku = f"🛟 {t('lifeline')}"
                    ukryta_instrukcja_jezykowa = "Odpowiedz po polsku." if st.session_state.lang == "pl" else "Respond in English."
                    ukryty_prompt = "UKRYTA KOMENDA OD SYSTEMU: Uczeń prosi o małą podpowiedź do obecnego etapu. Naprowadź go delikatnie i krótko (np. wskaż grupę leków, podaj typ objawu), ale pod żadnym pozorem nie podawaj gotowej diagnozy ani pełnej odpowiedzi."
                    
                    tekst_usera = t("lifeline_used").format(ile_podpowiedzi+1)
                    
                    if st.button(tekst_przycisku, use_container_width=True):
                        st.session_state.liczba_podpowiedzi += 1
                        st.session_state.messages.append({"role": "user", "content": tekst_usera})
                        
                        with st.spinner(t("spinner_tutor_hint")):
                            historia_bez_ostatniej = st.session_state.messages[:-1]
                            odpowiedz_tekst, nowa_sesja = wyslij_wiadomosc_kaskadowo(ukryty_prompt, historia_bez_ostatniej)
                            
                            if odpowiedz_tekst is None:
                                st.error(t("err_network"))
                                st.session_state.messages.pop()
                                st.session_state.liczba_podpowiedzi -= 1
                            else:
                                st.session_state.chat_session = nowa_sesja
                                st.session_state.messages.append({"role": "assistant", "content": odpowiedz_tekst})
                                st.rerun()
                else:
                    
                    st.button(t("lifeline_exhausted"), disabled=True, use_container_width=True)


            # GŁÓWNY CZAT
            if prompt := st.chat_input(t("chat_placeholder")):
                st.session_state.messages.append({"role": "user", "content": prompt})
                
                with st.chat_message("user", avatar=pobierz_awatar("user")):
                    st.markdown(prompt)
                    
                with st.chat_message("assistant", avatar=pobierz_awatar("assistant")):
                    if prompt.strip() == "Bingo IHK":
                        oszukana_odpowiedz = t('bingo_response')
                        st.markdown(oszukana_odpowiedz)
                        st.session_state.messages.append({"role": "assistant", "content": oszukana_odpowiedz})
                        st.session_state.zapisane_przypadki.append({
                            "wynik": "100",
                            "historia": list(st.session_state.messages)
                        })
                        obecna_kategoria = st.session_state.get('aktywna_kategoria', 'inne')
                        save_result_to_db(st.session_state.get('user_nick'), 100, st.session_state.messages, obecna_kategoria)
                        st.rerun()
                        
                    else:
                        with st.spinner(t("spinner_evaluating")):
                            historia_bez_ostatniej = st.session_state.messages[:-1]
                            odpowiedz_tekst, nowa_sesja = wyslij_wiadomosc_kaskadowo(prompt, historia_bez_ostatniej)
                            
                            if odpowiedz_tekst is None:
                                st.error(t("err_models_busy"))
                                st.session_state.messages.pop() 
                            else:
                                st.session_state.chat_session = nowa_sesja
                                
                                
                                if "```json" in odpowiedz_tekst:
                                    json_match = re.search(r"```json\s*(.*?)\s*```", odpowiedz_tekst, re.DOTALL)
                                    if json_match:
                                        try:
                                            dane = json.loads(json_match.group(1))
                                            for klucz in dane:
                                                if isinstance(dane[klucz], dict) and "komentarz" in dane[klucz]:
                                                    if isinstance(dane[klucz]["komentarz"], str):
                                                        # Agresywne czyszczenie z łamaczy linii dla Markdown
                                                        czysty_komentarz = dane[klucz]["komentarz"].replace("<br>", " ").replace("<br/>", " ")
                                                        czysty_komentarz = czysty_komentarz.replace("\n", " ").replace("\r", " ").strip()
                                                        dane[klucz]["komentarz"] = czysty_komentarz
                                                    else:
                                                        dane[klucz]["komentarz"] = ""
                                            
                                            suma_praktyka = (dane["zadanie_1_badania"]["wynik"] + 
                                                            dane["zadanie_2_interpretacja"]["wynik"] + 
                                                            dane["zadanie_2_diagnoza"]["wynik"] + 
                                                            dane["zadanie_2_roznicowa"]["wynik"] + 
                                                            dane["zadanie_2_leczenie"]["wynik"])
                                            srednia_praktyka = suma_praktyka / 5
                                            wynik_teoria = dane["zadanie_3_teoria"]["wynik"]
                                            
                                            wstepny_wynik = round((srednia_praktyka * 0.85) + (wynik_teoria * 0.15))
                                            kara_punkty = st.session_state.liczba_podpowiedzi * 10
                                            ostateczny_wynik = max(0, wstepny_wynik - kara_punkty)

                                            # --- DYNAMICZNE ETYKIETY TABELI ---
                                            kategoria_gry = st.session_state.get("aktywna_kategoria", "interna")
                                            jezyk_gry = st.session_state.get("lang", "pl")

                                            if kategoria_gry == "pediatria":
                                                etykieta_z1 = "Zad 1: Wywiad i Książeczka" if jezyk_gry == "pl" else "Task 1: Pediatric History"
                                                etykieta_z2_int = "Zad 2: Siatki / Skale" if jezyk_gry == "pl" else "Task 2: Growth Charts / Scales"
                                                etykieta_z2_diag = "Zad 2: Decyzja / Diagnoza" if jezyk_gry == "pl" else "Task 2: Decision / Diagnosis"
                                                etykieta_z2_roz = "Zad 2: Rozpoznanie stanu" if jezyk_gry == "pl" else "Task 2: Condition Recognition"
                                                etykieta_z2_lecz = "Zad 2: Leczenie i Dawki" if jezyk_gry == "pl" else "Task 2: Treatment & Dosages"
                                                etykieta_z3 = "Zad 3: Teoria / Szansa" if jezyk_gry == "pl" else "Task 3: Theory / 2nd Chance"
                                            elif kategoria_gry == "ratunkowa":
                                                etykieta_z1 = "Zad 1: Zlecone Badania" if jezyk_gry == "pl" else "Task 1: Ordered Tests"
                                                etykieta_z2_int = "Zad 2: Interpretacja EKG" if jezyk_gry == "pl" else "Task 2: ECG Interpretation"
                                                etykieta_z2_diag = "Zad 2: Precyzyjna Diagnoza" if jezyk_gry == "pl" else "Task 2: Precise Diagnosis"
                                                etykieta_z2_roz = "Zad 2: Zdecydowanie w działaniu" if jezyk_gry == "pl" else "Task 2: Decisiveness"
                                                etykieta_z2_lecz = "Zad 2: Postępowanie ratunkowe" if jezyk_gry == "pl" else "Task 2: Emergency Management"
                                                etykieta_z3 = "Zad 3: Teoria z OIT/SOR" if jezyk_gry == "pl" else "Task 3: ER Theory"
                                            else:
                                                etykieta_z1 = t('tbl_task1')
                                                etykieta_z2_int = t('tbl_task2_int')
                                                etykieta_z2_diag = t('tbl_task2_diag')
                                                etykieta_z2_roz = t('tbl_task2_diff')
                                                etykieta_z2_lecz = t('tbl_task2_treat')
                                                etykieta_z3 = t('tbl_task3')
                                            
                                            tabela_md = f"""
{t('tbl_header')}
| {etykieta_z1} | {dane['zadanie_1_badania']['komentarz']} | {dane['zadanie_1_badania']['wynik']}% |
| {etykieta_z2_int} | {dane['zadanie_2_interpretacja']['komentarz']} | {dane['zadanie_2_interpretacja']['wynik']}% |
| {etykieta_z2_diag} | {dane['zadanie_2_diagnoza']['komentarz']} | {dane['zadanie_2_diagnoza']['wynik']}% |
| {etykieta_z2_roz} | {dane['zadanie_2_roznicowa']['komentarz']} | {dane['zadanie_2_roznicowa']['wynik']}% |
| {etykieta_z2_lecz} | {dane['zadanie_2_leczenie']['komentarz']} | {dane['zadanie_2_leczenie']['wynik']}% |
| {etykieta_z3} | {dane['zadanie_3_teoria']['komentarz']} | {dane['zadanie_3_teoria']['wynik']}% |
| {t('tbl_hints')} | {t('tbl_hints_used').format(st.session_state.liczba_podpowiedzi)} | **-{kara_punkty}%** |

{t('tbl_final').format(ostateczny_wynik)}
"""
                                            st.markdown(tabela_md)
                                            st.session_state.messages.append({"role": "assistant", "content": tabela_md})
                                            
                                            st.session_state.zapisane_przypadki.append({
                                                "wynik": str(ostateczny_wynik),
                                                "historia": [dict(m) for m in st.session_state.messages]
                                            })
                                            
                                            
                                            obecna_kategoria = st.session_state.get('aktywna_kategoria', 'inne')
                                            save_result_to_db(st.session_state.get('user_nick'), ostateczny_wynik, st.session_state.messages, obecna_kategoria)
                                            
                                            st.rerun()
                                        except json.JSONDecodeError:
                                            st.error(t("error"))
                                            st.session_state.messages.pop()

                                elif "OSTATECZNY WYNIK" in odpowiedz_tekst.upper():
                                    st.markdown(odpowiedz_tekst)
                                    st.session_state.messages.append({"role": "assistant", "content": odpowiedz_tekst})
                                    wynik_match = re.search(r"OSTATECZNY WYNIK:\s*\*?\*?\s*(\d+)", odpowiedz_tekst, re.IGNORECASE)
                                    zlapany_wynik = wynik_match.group(1) if wynik_match else "?"
                                    st.session_state.zapisane_przypadki.append({
                                        "wynik": str(zlapany_wynik),
                                        "historia": [dict(m) for m in st.session_state.messages]
                                    })
                                    st.rerun()

                                else:
                                    st.session_state.messages.append({"role": "assistant", "content": odpowiedz_tekst})
                                    st.rerun()
# ZAKŁADKA: KONTO
with tab_konto:
    if not st.session_state.logged_in:
        
        col1, col2, col3 = st.columns([1, 2, 1]) 
        
        with col2:
            if not st.session_state.show_register:
                
                st.markdown(f"<h3 style='text-align: center;'>{t('login_header')}</h3>", unsafe_allow_html=True)
                log_user = st.text_input(t("login_input"), key="log_user_main")
                log_pass = st.text_input(t("pass_input"), type="password", key="log_pass_main")
                
                if st.button(t("btn_login"), use_container_width=True, type="primary"):
                    if login_user(log_user, log_pass):
                        st.session_state.logged_in = True
                        st.session_state.user_nick = log_user
                        
                        controller.set("tutor_osce_user", log_user, max_age=30*86400)

                        user_info = get_user_info(log_user)
                        st.session_state.user_email = user_info["email"]
                        
                        db_lang = user_info["language"]
                        if db_lang == "Polski": db_lang = "pl"
                        if db_lang == "English": db_lang = "en"
                        if not db_lang: db_lang = "pl"
                        
                        st.session_state.lang = db_lang
                        st.session_state.show_register = False 
                        st.rerun()
                    else:
                        st.error(t("no_login"))
                
                st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)
                st.markdown(f"<div style='text-align: center; color: #666;'>{t('no_account')}</div>", unsafe_allow_html=True)
                if st.button(t("btn_register"), use_container_width=True):
                    st.session_state.show_register = True
                    st.rerun()
                    
            else:
                
                st.markdown(f"<h3 style='text-align: center;'> {t('register_header')} </h3>", unsafe_allow_html=True)
                reg_user = st.text_input(t("create_login"), key="reg_user_main")
                reg_pass = st.text_input(t("create_pass"), type="password", key="reg_pass_main")
                
                if st.button(t("btn_create_account"), use_container_width=True, type="primary"):
                    if register_user(reg_user, reg_pass):
                        st.success(t("konto"))
                        st.session_state.show_register = False
                        st.rerun()
                    else:
                        st.error(t("repeat"))
                
                st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)
                st.markdown(f"<div style='text-align: center; color: #666;'>{t('account_yet')}</div>", unsafe_allow_html=True)
                if st.button(t("back_login"), use_container_width=True):
                    st.session_state.show_register = False
                    st.rerun()

    else:
        import time 
        
        st.markdown(
            f"""
            <div style="background-color: #EAF4EA; border-left: 6px solid #84B179; padding: 20px; border-radius: 8px; margin-bottom: 25px;">
                <h3 style="color: #1B211A; margin: 0;">Witaj ponownie, <span style="color: #088C6F;">{st.session_state.user_nick}</span>!</h3>
                <p style="margin: 5px 0 0 0; color: #555; font-size: 14px;">Zarządzaj swoimi danymi i ustawieniami konta poniżej.</p>
            </div>
            """, 
            unsafe_allow_html=True
        )
        
        # SEKCJA 1: DANE PROFILU I PREFERENCJE 
        users_base64 = __import__("base64").b64encode(open("ikony/users.png", "rb").read()).decode()
        st.markdown(
                f"""
                <div style="display: flex; align-items: center; margin-bottom: 20px;">
                    <img src="data:image/png;base64,{users_base64}" width="30" style="margin-right: 12px; vertical-align: middle;">
                    <h3 style="margin: 0; font-weight: 600; font-size: 1.25rem; color: #1B211A; vertical-align: middle;">Twoje dane i preferencje</h3>
                </div>
                """, 
                unsafe_allow_html=True
            )
        
        st.text_input("Nazwa użytkownika (Login)", value=st.session_state.user_nick, disabled=True)
        
        current_email = st.session_state.get("user_email", "")
        nowy_email = st.text_input("Adres e-mail", value=current_email)
        
        
        aktualny_kod = st.session_state.get("lang", "pl")
        opcje = {"pl": "Polski", "en": "English"}
        odwrotnie = {"Polski": "pl", "English": "en"}
        aktualna_nazwa = opcje.get(aktualny_kod, "Polski")
        
        wybrany_jezyk_nazwa = st.selectbox(
            "Domyślny język aplikacji", 
            ["Polski", "English"], 
            index=["Polski", "English"].index(aktualna_nazwa)
        )
            
        
        if st.button("Zapisz zmiany", type="primary", use_container_width=True):
            zmiany_wprowadzone = False
            
            
            if nowy_email != current_email:
                update_user_email(st.session_state.user_nick, nowy_email)
                st.session_state.user_email = nowy_email
                zmiany_wprowadzone = True
                
          
            nowy_kod = odwrotnie[wybrany_jezyk_nazwa]
            if nowy_kod != aktualny_kod:
                update_user_language(st.session_state.user_nick, nowy_kod)
                st.session_state.lang = nowy_kod
                st.session_state.chat_session = None 
                zmiany_wprowadzone = True
                
            if zmiany_wprowadzone:
                st.toast("Zmiany zostały pomyślnie zapisane!", icon="✅")
                time.sleep(1.2)
                st.rerun()
            else:
                st.toast("Brak zmian do zapisania.", icon="ℹ️")

        st.divider()

        # SEKCJA 2: ZARZĄDZANIE KONTEM (UKRYTE/ZWIJANE)
        st.subheader("⚙️ Zarządzanie kontem")
        
        with st.expander("🔑 Zmień hasło"):
            col_old, col_new = st.columns(2)
            with col_old:
                old_p = st.text_input("Stare hasło", type="password", key="old_p")
            with col_new:
                new_p = st.text_input("Nowe hasło", type="password", key="new_p")
            
            if st.button("Zaktualizuj hasło"):
                if old_p and new_p:
                    if update_password(st.session_state.user_nick, old_p, new_p):
                        st.success("Hasło zostało zmienione pomyślnie!")
                    else:
                        st.error("Błędne stare hasło lub błąd aktualizacji.")
                else:
                    st.warning("Proszę wypełnić oba pola.")

        # Usunięcie konta
        with st.expander("🚨 Usuń konto"):
            st.error("Uwaga: Usunięcie konta jest nieodwracalne. Utracisz wszystkie swoje dane oraz historię wyników.")
            
            potwierdzenie = st.text_input(f"Aby potwierdzić, wpisz swój login: {st.session_state.user_nick}")
            
            if st.button("Trwale usuń moje konto", type="primary"):
                if potwierdzenie == st.session_state.user_nick:
                    delete_user_account(st.session_state.user_nick)
                    st.session_state.logged_in = False
                    st.session_state.user_nick = None
                    st.session_state.user_email = ""
                    st.warning("Twoje konto zostało usunięte.")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("Podany login nie pasuje. Operacja przerwana.")

        st.divider()

        # SEKCJA 3: WYLOGOWANIE
        col_pusta1, col_wyloguj, col_pusta2 = st.columns([1, 2, 1])
        with col_wyloguj:
            if st.button("🚪 Wyloguj się", use_container_width=True):
                controller.remove("tutor_osce_user")
                st.session_state.logged_in = False
                st.session_state.user_nick = None
                st.session_state.user_email = ""
                st.session_state.show_register = False
                st.rerun()

# zakładka postępy
with tab_statystyki:
    current_user = st.session_state.get('user_nick')
    if current_user:
        conn = sqlite3.connect('osce_history.db')
        df = pd.read_sql_query("SELECT id, date, score, history, category FROM results WHERE username = ? ORDER BY id DESC", conn, params=(current_user,))
        conn.close()

        if not df.empty:
            if 'category' not in df.columns:
                df['category'] = 'inne'
            else:
                df['category'] = df['category'].fillna('inne')
            
            KOLORY_KAT = {
                "interna": "#AACDDC",
                "pedsy": "#FFF2C6",
                "ratunkowa": "#EA907A",
                "inne": "#F5F0E6",
                "wlasne": "#F5F0E6"
            }
            IKONY_KAT = {
                "interna": "🩺",
                "pedsy": "🧸",
                "ratunkowa": "🚑",
                "inne": "📁",
                "wlasne": "📁"
            }
            
            PULA_PRZYPADKOW = {}
            try:
                import os
                import json
                
                if os.path.exists("my_notes"):
                    for plik in os.listdir("my_notes"):
                        if plik.endswith(".json"):
                            kat = plik.replace(".json", "").lower()
                            with open(os.path.join("my_notes", plik), "r", encoding="utf-8") as f:
                                przypadki_w_pliku = json.load(f)
                                PULA_PRZYPADKOW[kat] = len(przypadki_w_pliku)
            except Exception:
                pass 
                
            try:
                ile_wlasnych = len([c for c in lista_wszystkich_chorob if c.get("kategoria") == "wlasne"])
                if ile_wlasnych > 0:
                    PULA_PRZYPADKOW["wlasne"] = ile_wlasnych
            except NameError:
                pass
                
            calkowita_pula = sum(PULA_PRZYPADKOW.values())

            # --- KPI
            def duzy_kafelek(wartosc, opis, bg_color="#F5F0E6", text_color="#1B211A"):
                return f"""
                <div style="background-color: {bg_color}; border-radius: 10px; padding: 20px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 10px; height: 110px; display: flex; flex-direction: column; justify-content: center; border: 1px solid rgba(0,0,0,0.05);">
                    <div style="font-size: 2.8rem; font-weight: 900; color: {text_color}; line-height: 1;">{wartosc}</div>
                    <div style="font-size: 0.8rem; font-weight: 800; color: rgba(27, 33, 26, 0.75); text-transform: uppercase; margin-top: 8px; letter-spacing: 0.5px;">{opis}</div>
                </div>
                """

            try:
                business_base64 = __import__("base64").b64encode(open("ikony/business.png", "rb").read()).decode()
            except FileNotFoundError:
                business_base64 = ""
                
            st.markdown(
                f"""
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px;">
                    <img src="data:image/png;base64,{business_base64}" width="30">
                    <h3 style="margin: 0; color: #1B211A;">{t('stat_title')} <span style='color: #088C6F;'>{current_user}</span></h3>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
            if "kpi_cat_idx" not in st.session_state:
                st.session_state.kpi_cat_idx = 0
            if "kpi_best_idx" not in st.session_state:
                st.session_state.kpi_best_idx = 0 
                
            kpi_categories = [t('kpi_overall')] + df['category'].unique().tolist()
            if st.session_state.kpi_cat_idx >= len(kpi_categories):
                st.session_state.kpi_cat_idx = 0
                
            current_kpi_cat = kpi_categories[st.session_state.kpi_cat_idx]
            df_kpi = df if current_kpi_cat == t('kpi_overall') else df[df['category'] == current_kpi_cat]
            
           
            display_kpi_cat = current_kpi_cat if current_kpi_cat == t('kpi_overall') else t(f"cat_{current_kpi_cat}")
            
            col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
            
            with col_kpi1:
                etykieta_ilosci = f"{t('kpi_cases')} ({display_kpi_cat})"
                st.markdown(duzy_kafelek(len(df_kpi), etykieta_ilosci), unsafe_allow_html=True)
                
            with col_kpi2:
                srednia_kat = df_kpi['score'].mean() if not df_kpi.empty else 0
                kolor_tla_kpi = KOLORY_KAT.get(current_kpi_cat, "#F5F0E6") if current_kpi_cat != t('kpi_overall') else "#F5F0E6"
                etykieta_sredniej = f"📊 {t('kpi_avg')} ({display_kpi_cat})"
                
                st.markdown(duzy_kafelek(f"{round(srednia_kat)}%", etykieta_sredniej, bg_color=kolor_tla_kpi), unsafe_allow_html=True)
                
                if len(kpi_categories) > 1:
                    c2_l, c2_m, c2_r = st.columns([1, 3, 1])
                    with c2_l:
                        if st.button("◀", key="prev_cat", help=t('kpi_prev'), use_container_width=True):
                            st.session_state.kpi_cat_idx = (st.session_state.kpi_cat_idx - 1) % len(kpi_categories)
                            st.rerun()
                    with c2_r:
                        if st.button("▶", key="next_cat", help=t('kpi_next'), use_container_width=True):
                            st.session_state.kpi_cat_idx = (st.session_state.kpi_cat_idx + 1) % len(kpi_categories)
                            st.rerun()
                            
            with col_kpi3:
                is_best = (st.session_state.kpi_best_idx == 0)
                score_val = df_kpi['score'].max() if is_best and not df_kpi.empty else (df_kpi['score'].min() if not df_kpi.empty else 0)
                ikona_rekordu = t('kpi_best') if is_best else t('kpi_worst')
                etykieta_rekordu = f"{ikona_rekordu} ({display_kpi_cat})"
                
                st.markdown(duzy_kafelek(f"{score_val}%", etykieta_rekordu), unsafe_allow_html=True)
                
                c3_l, c3_m, c3_r = st.columns([1, 3, 1])
                with c3_l:
                    if st.button("◀", key="prev_best", help=t('kpi_toggle'), use_container_width=True):
                        st.session_state.kpi_best_idx = 1 - st.session_state.kpi_best_idx
                        st.rerun()
                with c3_r:
                    if st.button("▶", key="next_best", help=t('kpi_toggle'), use_container_width=True):
                        st.session_state.kpi_best_idx = 1 - st.session_state.kpi_best_idx
                        st.rerun()
                
            st.divider()
            
            # --- 2. ZAKŁADKI Z WYKRESAMI ---
            if len(df) >= 3:
                tab_trend, tab_kat, tab_rozklad = st.tabs([t('tab_trend'), t('tab_avg_cat'), t('tab_dist')])
                
                with tab_trend:
                    chart_data = df.copy().sort_values('date')
                    base = alt.Chart(chart_data).encode(
                        x=alt.X('date', title=t("date_simulation"), axis=alt.Axis(labelAngle=-45)),
                        y=alt.Y('score', title=t("score_label"), scale=alt.Scale(domain=[0, 100])),
                        tooltip=[alt.Tooltip('date', title=t("date_simulation")), alt.Tooltip('score', title=t("score_label")), alt.Tooltip('category', title=t("lbl_category"))]
                    )
                    line = base.mark_line(color='#84B179', size=3)
                    points = base.mark_circle(color='#088C6F', size=80)
                    st.altair_chart((line + points).properties(height=350), use_container_width=True)
                    
                with tab_kat:
                    bar_data = df.groupby('category')['score'].mean().reset_index()
                    color_scale = alt.Scale(
                        domain=list(KOLORY_KAT.keys()),
                        range=list(KOLORY_KAT.values())
                    )
                    bar_chart = alt.Chart(bar_data).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
                        x=alt.X('category', title=t("lbl_category"), sort='-y', axis=alt.Axis(labelAngle=0)),
                        y=alt.Y('score', title=t("lbl_avg_score"), scale=alt.Scale(domain=[0, 100])),
                        color=alt.Color('category', scale=color_scale, legend=None),
                        tooltip=[alt.Tooltip('category', title=t("lbl_category")), alt.Tooltip('score', title=t("kpi_avg"))]
                    ).properties(height=350)
                    st.altair_chart(bar_chart, use_container_width=True)
                    
                with tab_rozklad:
                    pie_data = df['category'].value_counts().reset_index()
                    pie_data.columns = ['category', 'count']
                    
                    pie_color_scale = alt.Scale(
                        domain=list(KOLORY_KAT.keys()),
                        range=list(KOLORY_KAT.values())
                    )
                    
                    pie_chart = alt.Chart(pie_data).mark_arc(innerRadius=60, stroke="#fff", strokeWidth=2).encode(
                        theta=alt.Theta(field="count", type="quantitative"),
                        color=alt.Color(field="category", type="nominal", scale=pie_color_scale, legend=alt.Legend(title=t("lbl_category"), orient="right", titleFontSize=14, labelFontSize=12)),
                        tooltip=[alt.Tooltip('category', title=t("lbl_category")), alt.Tooltip('count', title=t("lbl_cases_count"))]
                    ).properties(height=350)
                    
                    st.altair_chart(pie_chart, use_container_width=True)
            else:
                st.markdown(
                    f"""
                    <div style="background-color: #F5F0E6; border-left: 5px solid #84B179; padding: 15px; border-radius: 4px; color: #1B211A; font-size: 15px;">
                       {t("chart_wait").format(len(df))}
                    </div>
                    """, 
                    unsafe_allow_html=True
                )

            st.divider()
            
            # --- 3. FILTROWANIE I ARCHIWUM ---
            try:
                writing_base64 = __import__("base64").b64encode(open("ikony/writing.png", "rb").read()).decode()
            except FileNotFoundError:
                writing_base64 = ""
                
            st.markdown(
                f"""
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">
                    <img src="data:image/png;base64,{writing_base64}" width="30">
                    <h3 style="margin: 0; color: #1B211A;">{t("resolved_cases")}</h3>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
            col_filtr, _ = st.columns([1, 2])
            with col_filtr:
                opcje_filtru = [t("filter_all")] + df['category'].unique().tolist()
                filtr_kategorii = st.selectbox(t("filter_history"), opcje_filtru, key="history_filter")
                
            df_filtered = df if filtr_kategorii == t("filter_all") else df[df['category'] == filtr_kategorii]
            
            if filtr_kategorii == t("filter_all"):
                kat_ikona_filtr = "🌍"
                kolor_tla_filtr = "#EAF4EA"
                tytul_banera = t("summary_all")
                pula_docelowa = calkowita_pula if calkowita_pula > 0 else len(df)
            else:
                kat_ikona_filtr = IKONY_KAT.get(filtr_kategorii, "📁")
                kolor_tla_filtr = KOLORY_KAT.get(filtr_kategorii, "#F5F0E6")
                tytul_banera = f"{t('summary_cat')} {t(f'cat_{filtr_kategorii}').upper()}"
                pula_docelowa = PULA_PRZYPADKOW.get(filtr_kategorii, len(df_filtered))
                if pula_docelowa == 0: pula_docelowa = len(df_filtered) if len(df_filtered) > 0 else 1

            st.markdown(f"""
            <div style="background-color: {kolor_tla_filtr}; padding: 12px 20px; border-radius: 8px; margin-bottom: 15px; border-left: 6px solid rgba(0,0,0,0.15); display: flex; align-items: center;">
                <span style="color: #1B211A; font-weight: 800; font-size: 1.1rem; letter-spacing: 0.5px;">{kat_ikona_filtr} {tytul_banera}</span>
            </div>
            """, unsafe_allow_html=True)
            
            c1, c2, c3, c4 = st.columns(4)
            
            def mini_kafelek(wartosc, opis):
                return f"""
                <div style="background-color: #F9F9F9; border-left: 4px solid #088C6F; padding: 10px; border-radius: 4px; margin-bottom: 15px;">
                    <div style="font-size: 11px; color: #7f8c8d; text-transform: uppercase; font-weight: bold;">{opis}</div>
                    <div style="font-size: 1.4rem; color: #1B211A; font-weight: 800;">{wartosc}</div>
                </div>
                """
            
            max_score = df_filtered['score'].max() if not df_filtered.empty else 0
            min_score = df_filtered['score'].min() if not df_filtered.empty else 0
            avg_score = round(df_filtered['score'].mean()) if not df_filtered.empty else 0
            
            wykonane_przypadki = len(df_filtered)
            procent_ukonczenia = min((wykonane_przypadki / pula_docelowa) * 100, 100) if pula_docelowa > 0 else 0
            
            c1.markdown(mini_kafelek(f"{max_score}%", t("kpi_best")), unsafe_allow_html=True)
            c2.markdown(mini_kafelek(f"{min_score}%", t("kpi_worst")), unsafe_allow_html=True)
            c3.markdown(mini_kafelek(f"{avg_score}%", f"📊 {t('kpi_avg')}"), unsafe_allow_html=True)
            c4.markdown(mini_kafelek(f"{wykonane_przypadki} / {pula_docelowa}", f"{t('lbl_completed')} ({procent_ukonczenia:.0f}%)"), unsafe_allow_html=True)
            
            for i, row in df_filtered.iterrows():
                kat = row['category']
                kat_ikona = IKONY_KAT.get(kat, "📁")
                kolor_tla = KOLORY_KAT.get(kat, "#F5F0E6")
                kat_display = t(f"cat_{kat}")
                
                with st.expander(f"{kat_ikona} {row['date']} | {kat_display.upper()} — {t('report_score')} {row['score']}%"):
                    
                    st.markdown(f"""
                    <div style="background-color: {kolor_tla}; padding: 12px 20px; border-radius: 8px; margin-bottom: 20px; border-left: 6px solid rgba(0,0,0,0.15); display: flex; justify-content: space-between; align-items: center;">
                        <span style="color: #1B211A; font-weight: 800; font-size: 1.1rem; letter-spacing: 0.5px;">{kat_ikona} {kat_display.upper()}</span>
                        <span style="background-color: rgba(255,255,255,0.7); padding: 4px 12px; border-radius: 20px; font-weight: 800; color: #1B211A; font-size: 0.9rem;">{t('lbl_saved_score')} {row['score']}%</span>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if pd.notna(row['history']) and row['history']:
                        try:
                            case_history = json.loads(row['history'])
                            for message in case_history:
                                with st.chat_message(message["role"], avatar=pobierz_awatar(message["role"])):
                                    if 'renderuj_wiadomosc' in globals() or 'renderuj_wiadomosc' in locals():
                                        renderuj_wiadomosc(message)
                                    else:
                                        st.markdown(message["content"])
                        except json.JSONDecodeError:
                            st.error(t("error"))
                    else:
                        st.write(t("stara_baza"))
        else:
            st.markdown(f"""
                <div style="background-color: #F5F0E6; border-left: 5px solid #84B179; padding: 15px; border-radius: 4px; color: #1B211A; font-size: 15px;">
                    {t('stat1')}
                </div>
                """, 
                unsafe_allow_html=True
            )
    else:
        st.markdown(f"""
        <div style="background-color: #EAF4EA; border-left: 5px solid #84B179; padding: 12px; border-radius: 4px; color: #1B211A; font-size: 14px; margin-bottom: 10px;">
            {t('login_prompt')}
        </div>
        """, 
        unsafe_allow_html=True
        )
