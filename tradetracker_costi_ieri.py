import os
import time
import logging
# L'import 'calendar' non è più necessario con la nuova logica
from datetime import datetime, timedelta # <-- 1. MODIFICA: Aggiunto timedelta
from flask import Flask, request
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from google.cloud import storage

# Configura l'app Flask
app = Flask(__name__)

# Configura il logging per vedere i messaggi in console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def upload_to_gcs(bucket_name, source_file_name, destination_blob_name):
    """Carica un file su Google Cloud Storage."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)
    logger.info(f"File {source_file_name} caricato come {destination_blob_name} nel bucket {bucket_name}.")
    return blob.name

def get_latest_csv(directory):
    """Restituisce il file CSV più recente nella directory specificata."""
    csv_files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith('.csv')]
    if not csv_files:
        raise Exception("Nessun file CSV trovato nella directory.")
    latest_file = max(csv_files, key=os.path.getctime)
    return latest_file

def run_selenium_script(username, password, folder_id):
    """
    Funzione che apre il browser in modalità headless, naviga alla pagina di login di TradeTracker,
    inserisce username e password, naviga alla pagina delle vendite, e poi:
      - clicca sul menù a tendina (usando l'XPath "//*[@id='s2id_predefined-periods-p']/a")
      - attende che compaia l'elemento con XPath "//*[@id='select2-drop']"
      - clicca sull'elemento interno con XPath "//*[@id='select2-results-1']/li[8]" e logga il risultato
      - clicca sul bottone per esportare il CSV e scatta uno screenshot subito dopo il click (che viene caricato su GCS)
      - attende il download del CSV, rinomina il file e lo carica su GCS
    Al termine restituisce il nome del file creato.
    In caso di errore, cattura uno screenshot e lo carica su Cloud Storage.
    """
    logger.info("Avvio dello script Selenium.")
    driver = None
    download_dir = "/tmp"
    new_filename = None

    try:
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1920,1080')
        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True
        }
        options.add_experimental_option("prefs", prefs)
        
        logger.info("Inizializzazione del driver Chrome.")
        driver = webdriver.Chrome(options=options)
        logger.info("Driver Chrome inizializzato correttamente.")
        
        login_url = "https://merchant.tradetracker.com/user/login"
        logger.info(f"Navigazione verso la pagina di login: {login_url}")
        driver.get(login_url)
        logger.info("Pagina di login caricata, attesa di 8 secondi per il rendering completo.")
        time.sleep(8)
        
        username_xpath = "//*[@id='username']"
        username_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, username_xpath))
        )
        username_field.send_keys(username)
        
        password_xpath = "//*[@id='password']"
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, password_xpath))
        )
        password_field.send_keys(password)
        
        login_button_xpath = "//*[@id='submitLogin']"
        login_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, login_button_xpath))
        )
        login_button.click()
        logger.info("Login eseguito.")
        time.sleep(5)
        
        sales_url = "https://merchant.tradetracker.com/affiliateTransaction/sales"
        logger.info(f"Navigazione verso la pagina delle vendite: {sales_url}")
        driver.get(sales_url)
        logger.info("Pagina delle vendite caricata, attesa di 8 secondi per il rendering completo.")
        time.sleep(8)
        
        dropdown_xpath = "//*[@id='s2id_predefined-periods-p']/a"
        dropdown = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, dropdown_xpath))
        )
        dropdown.click()
        logger.info("Menù a tendina cliccato.")
        time.sleep(2)
        
        option_text_to_find = "Ieri"
        option_xpath = f"//div[@id='select2-drop']//li[div[contains(text(), '{option_text_to_find}')]]"
        logger.info(f"Ricerca e clic sull'opzione che contiene il testo: '{option_text_to_find}'")
        option_element = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, option_xpath))
        )
        option_element.click()
        logger.info(f"Elemento '{option_text_to_find}' cliccato con successo.")
        time.sleep(2) 
        
        export_csv_xpath = "//*[@id='listview-10-export-csv']"
        export_csv_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, export_csv_xpath))
        )
        export_csv_button.click()
        logger.info("Bottone di export CSV cliccato.")
        
        logger.info("Attesa di 90 secondi per il download del CSV.")
        time.sleep(90)
        
        latest_csv = get_latest_csv(download_dir)
        logger.info(f"CSV scaricato individuato: {latest_csv}")
        
        # --- INIZIO BLOCCO MODIFICATO ---
        # 2. MODIFICA: Calcola la data di ieri e formatta il nome del file
        yesterday = datetime.today() - timedelta(days=1)
        new_filename = f"{yesterday.strftime('%Y-%m-%d')}.csv"
        # --- FINE BLOCCO MODIFICATO ---

        new_filepath = os.path.join(download_dir, new_filename)
        logger.info(f"Rinominazione del file in: {new_filepath}")
        os.rename(latest_csv, new_filepath)
        
        destination_blob_name = f"{folder_id}/{new_filename}"
        logger.info(f"Upload del file nel bucket 'tradetracker_selenium' nella cartella '{folder_id}' con nome blob: {destination_blob_name}")
        
        upload_to_gcs("tradetracker_selenium", new_filepath, destination_blob_name)
        
        return new_filename
        
    except Exception as e:
        logger.error(f"Errore durante l'esecuzione di Selenium: {repr(e)}")
        if driver is not None:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                error_screenshot = os.path.join(download_dir, f"error_{timestamp}.png")
                driver.save_screenshot(error_screenshot)
                destination_blob_error = f"{folder_id}/error_{timestamp}.png"
                upload_to_gcs("tradetracker_selenium", error_screenshot, destination_blob_error)
                logger.info(f"Screenshot di errore caricato come {destination_blob_error}.")
            except Exception as screenshot_error:
                logger.error(f"Errore nel catturare o caricare lo screenshot: {repr(screenshot_error)}")
        return None
    finally:
        if driver is not None:
            logger.info("Chiusura del driver Chrome.")
            driver.quit()
            logger.info("Driver chiuso.")

@app.route('/run-selenium', methods=['GET'])
def call_selenium():
    logger.info("Ricevuta richiesta per eseguire /run-selenium.")
    
    username = request.args.get('username')
    password = request.args.get('password')
    folder_id = request.args.get('folder_id')
    
    if not all([username, password, folder_id]):
        logger.error("Parametri mancanti: assicurarsi di passare username, password e folder_id.")
        return "username, password e folder_id sono richiesti", 400
    
    result_filename = run_selenium_script(username, password, folder_id)
    logger.info("Script Selenium eseguito. Risposta inviata.")
    if result_filename:
        return result_filename, 200
    else:
        return "Errore nell'esecuzione dello script", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Avvio dell'app Flask sulla porta {port}.")
    app.run(host='0.0.0.0', port=port)
