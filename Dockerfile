# Usa una versione di Python più recente e specifica per la riproducibilità
FROM python:3.11-slim

# Imposta variabili d'ambiente per evitare output interattivi durante l'installazione
ENV DEBIAN_FRONTEND=noninteractive

# Installa le dipendenze di sistema, ottimizzando per le dimensioni
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    unzip \
    curl \
    chromium \
    chromium-driver \
    # Pulisce la cache di apt per ridurre le dimensioni dell'immagine
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Imposta la directory di lavoro
WORKDIR /app

# Copia prima il file delle dipendenze per sfruttare la cache di Docker
COPY requirements.txt .

# Aggiorna pip e installa le librerie Python senza cache
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia il resto dei file dell'applicazione
COPY . .

# Comando per avviare il server Gunicorn con configurazione per produzione
# Aumentato il timeout a 300 secondi per operazioni lunghe
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:8080", "--timeout", "300", "tradetracker_scraper:app"]
