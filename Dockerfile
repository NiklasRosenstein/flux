FROM ubuntu:16.04
ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && apt-get install -y git python3 python3-dev virtualenv gcc libffi-dev libssl-dev
RUN mkdir /app && mkdir /data
RUN virtualenv -p python3 /venv
ADD requirements.txt /app
RUN /venv/bin/pip install -r /app/requirements.txt
COPY . /app/
ENV PYTHONPATH /app
CMD /venv/bin/python3 /app/flux_run.py
