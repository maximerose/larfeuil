FROM python:3.14-slim

# Installation de Node.js pour compiler Tailwind lors du build
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installation des dépendances Python et Node
COPY requirements.txt package*.json ./
RUN pip install --no-cache-dir -r requirements.txt
RUN npm ci

COPY . .

# Compilation du CSS Tailwind minifié pour la prod
RUN npm run tailwind:build

CMD [ "python", "./main.py" ]
