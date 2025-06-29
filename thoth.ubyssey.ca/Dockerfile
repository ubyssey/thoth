FROM  python:3.11.12-bullseye

ENV PYTHONUNBUFFERED=1

COPY . /workspaces/thoth.ubyssey.ca/

WORKDIR /workspaces/thoth.ubyssey.ca/

RUN pip install -r requirements.txt

EXPOSE 8000