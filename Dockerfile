FROM  python:3.11.12-bullseye

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get -y install cron

COPY . /workspaces/backend/

WORKDIR /workspaces/backend/

RUN pip install -r requirements.txt

EXPOSE 8000