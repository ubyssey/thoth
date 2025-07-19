FROM  python:3.11.12-bullseye

ENV PYTHONUNBUFFERED=1

RUN apt update
RUN apt-get install cron -y

COPY . /workspaces/backend/

WORKDIR /workspaces/backend/

RUN pip install -r requirements.txt

EXPOSE 8000