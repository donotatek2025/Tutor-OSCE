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
from database import register_user, login_user, update_password, save_result_to_db
from ai_core import wyslij_wiadomosc_kaskadowo
from utils import wczytaj_i_podziel_pdf, pobierz_awatar, pobierz_grafike_base64

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
if "show_register" not in st.session_state:
    st.session_state.show_register = False
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": t("welcome_msg")}]
    st.session_state.historia_wynikow = []
if "zapisane_przypadki" not in st.session_state:
    st.session_state.zapisane_przypadki = []
if "widok_archiwum" not in st.session_state:
    st.session_state.widok_archiwum = None

if "widok_archiwum" not in st.session_state:
    st.session_state.widok_archiwum = None
if "liczba_podpowiedzi" not in st.session_state:
    st.session_state.liczba_podpowiedzi = 0

if "lang" not in st.session_state:
    st.session_state.lang = "pl"
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": t("welcome_msg")}]

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
            

                nazwa_wyswietlana = nazwa_pliku.replace(".json", "")
                ile_przypadkow = len(choroby_domyslne)
                
            
                czy_aktywna = st.toggle(
                    f" **{nazwa_wyswietlana}** ({ile_przypadkow} {t('cases_count')})",
                    value=True, 
                    key=f"toggle_{nazwa_pliku}"
                )
                
            
                if czy_aktywna:
                    lista_wszystkich_chorob.extend(choroby_domyslne)

        st.divider()

    
        wgrany_plik = st.file_uploader(t("upload_pdf"), type=["pdf"], key="pdf_uploader_baza")
        
        if wgrany_plik is not None:
            choroby_dodatkowe = wczytaj_i_podziel_pdf(wgrany_plik)
            lista_wszystkich_chorob.extend(choroby_dodatkowe)
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
            
            wylosowana_choroba = random.choice(lista_wszystkich_chorob)
            
            if st.session_state.lang == "pl":
                prompt_startowy = f"Prowadź całą symulację, odpowiadaj, oceniaj i zadawaj pytania WYŁĄCZNIE w języku polskim.\n\nOto opis wylosowanej jednostki chorobowej z moich notatek:\n\n{wylosowana_choroba}\n\nPrzeanalizuj ją po cichu i od razu rozpocznij ze mną Zadanie 1 (Opis pacjenta)."
            else:
                prompt_startowy = f"Conduct the entire simulation, respond, evaluate, and ask questions EXCLUSIVELY in English.\n\nHere is the description of the drawn disease from my notes:\n\n{wylosowana_choroba}\n\nAnalyze it silently and immediately start Task 1 (Patient description) with me."
            
            odpowiedz_tekst, nowa_sesja = wyslij_wiadomosc_kaskadowo(prompt_startowy, [])
            
            
            odpowiedz_tekst, nowa_sesja = wyslij_wiadomosc_kaskadowo(prompt_startowy, [])
            
            if odpowiedz_tekst:
                st.session_state.chat_session = nowa_sesja
                st.session_state.messages.append({"role": "assistant", "content": odpowiedz_tekst})
                st.rerun()
            else:
                st.error(t("err_models_busy"))
                
    if len(lista_wszystkich_chorob) > 0:
        st.markdown(
        f"""
        <div style="background-color: #EAF4EA; border-left: 5px solid #84B179; padding: 12px; border-radius: 4px; color: #1B211A; font-size: 14px; margin-bottom: 10px;">
            {t('available_cases')}:<span style="color: #088C6F; font-weight: bold;"> {len(lista_wszystkich_chorob)} </span>
        </div>
        """, 
        unsafe_allow_html=True
        )


    st.caption(t("tip_refresh"))
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
        pl_img_path = os.path.join(ICONS_PATH, "poland.png")
        pl_img = __import__("base64").b64encode(open(pl_img_path, "rb").read()).decode()
        en_img_path = os.path.join(ICONS_PATH, "british.png")
        en_img = __import__("base64").b64encode(open("british.png", "rb").read()).decode()
    
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
                st.markdown(message["content"])
                
    else:
        for message in st.session_state.messages:
            with st.chat_message(message["role"], avatar=pobierz_awatar(message["role"])):
                st.markdown(message["content"])

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
                        save_result_to_db(st.session_state.get('user_nick'), 100, st.session_state.messages)
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
                                                        dane[klucz]["komentarz"] = dane[klucz]["komentarz"].replace("<br>", " ").replace("<br/>", " ").replace("\n", " ")
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
                                            
                                            tabela_md = f"""
{t('tbl_header')}
| {t('tbl_task1')} | {dane['zadanie_1_badania']['komentarz']} | {dane['zadanie_1_badania']['wynik']}% |
| {t('tbl_task2_int')} | {dane['zadanie_2_interpretacja']['komentarz']} | {dane['zadanie_2_interpretacja']['wynik']}% |
| {t('tbl_task2_diag')} | {dane['zadanie_2_diagnoza']['komentarz']} | {dane['zadanie_2_diagnoza']['wynik']}% |
| {t('tbl_task2_diff')} | {dane['zadanie_2_roznicowa']['komentarz']} | {dane['zadanie_2_roznicowa']['wynik']}% |
| {t('tbl_task2_treat')} | {dane['zadanie_2_leczenie']['komentarz']} | {dane['zadanie_2_leczenie']['wynik']}% |
| {t('tbl_task3')} | {dane['zadanie_3_teoria']['komentarz']} | {dane['zadanie_3_teoria']['wynik']}% |
| {t('tbl_hints')} | {t('tbl_hints_used').format(st.session_state.liczba_podpowiedzi)} | **-{kara_punkty}%** |

{t('tbl_final').format(ostateczny_wynik)}
"""
                                            st.markdown(tabela_md)
                                            st.session_state.messages.append({"role": "assistant", "content": tabela_md})
                                            
                                            st.session_state.zapisane_przypadki.append({
                                                "wynik": str(ostateczny_wynik),
                                                "historia": [dict(m) for m in st.session_state.messages]
                                            })
                                            save_result_to_db(st.session_state.get('user_nick'), ostateczny_wynik, st.session_state.messages)
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
        
        st.markdown(
            f"""
            <div style="background-color: #EAF4EA; border-left: 6px solid #84B179; padding: 20px; border-radius: 8px; margin-bottom: 25px;">
                <h3 style="color: #1B211A; margin: 0;">{t('hello2')} <span style="color: #088C6F;">{st.session_state.user_nick}</span>!</h3>
                <p style="margin: 5px 0 0 0; color: #555; font-size: 14px;">{t('hello3')}</p>
            </div>
            """, 
            unsafe_allow_html=True
        )
        
    
        with st.expander(t("change_pass")):
            old_p = st.text_input(t("old_pass"), type="password", key="old_p")
            new_p = st.text_input(t("new_pass"), type="password", key="new_p")
            if st.button(t("update_btn")):
                if old_p and new_p:
                    if update_password(st.session_state.user_nick, old_p, new_p):
                        st.success(t("success_pass"))
                    else:
                        st.error(t("bad_pass"))
                else:
                    st.warning(t("daj2"))
        
        st.divider()
        
        col_wyloguj, _ = st.columns([1, 3])
        with col_wyloguj:
            if st.button(t("btn_logout"), use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.user_nick = None
                st.session_state.show_register = False
                st.rerun()


 # zakładka postępy
with tab_statystyki:
    current_user = st.session_state.get('user_nick')
    if current_user:
        conn = sqlite3.connect('osce_history.db')
        df = pd.read_sql_query("SELECT id, date, score, history FROM results WHERE username = ? ORDER BY id DESC", conn, params=(current_user,))
        conn.close()

        if not df.empty:
            business_base64 = __import__("base64").b64encode(open("ikony/business.png", "rb").read()).decode()
            st.markdown(
                f"""
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px;">
                    <img src="data:image/png;base64,{business_base64}" width="30">
                    <h3 style="margin: 0; color: #1B211A;">{t("stat_title")}: <span style='color: #088C6F;'>{current_user}</span></h3>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
            
            if len(df) >= 3:
                chart_data = df.copy().sort_values('date')
                
                
                base = alt.Chart(chart_data).encode(
                    x=alt.X('date', title=t("date_simulation"), axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y('score', title=t("score_label"), scale=alt.Scale(domain=[0, 100])),
                    tooltip=[alt.Tooltip('date', title=t("date_simulation")), alt.Tooltip('score', title=t("score_label"))]
                )
                
                line = base.mark_line(color='#84B179', size=3)
                points = base.mark_circle(color='#088C6F', size=80)
                
                
                final_chart = (line + points).properties(height=350)
                st.altair_chart(final_chart, use_container_width=True)
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
            writing_base64 = __import__("base64").b64encode(open("ikony/writing.png", "rb").read()).decode()
            st.markdown(
                f"""
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px;">
                    <img src="data:image/png;base64,{writing_base64}" width="30">
                    <h3 style="margin: 0; color: #1B211A;">{t("resolved_cases")}</h3>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
            
            for i, row in df.iterrows():
                with st.expander(f"⏱ {row['date']} — {t('report_score')} {row['score']}%"):
                    
                    if pd.notna(row['history']) and row['history']:
                        try:
                            case_history = json.loads(row['history'])
                            for message in case_history:
                                with st.chat_message(message["role"], avatar=pobierz_awatar(message["role"])):
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
