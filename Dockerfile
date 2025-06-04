# Используем официальный Python 3.10 slim образ
FROM python:3.10-slim

# Обновляем apt и ставим нужные библиотеки для сборки зависимостей
RUN apt-get update && apt-get install -y gcc libffi-dev libssl-dev

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Обновляем pip и ставим зависимости
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Копируем весь проект
COPY . .

# Команда запуска (замени main.py на твой файл, если нужно)
CMD ["python", "main.py"]
