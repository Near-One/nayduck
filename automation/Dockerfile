FROM ubuntu:latest


RUN --mount=type=secret,id=auth
RUN --mount=type=secret,id=database 

RUN apt-get update

RUN apt-get -y install fdisk git python3-pip libpq-dev lld libclang-dev

RUN git clone https://github.com/near/nayduck.git

RUN pip install -r nayduck/requirements.txt 

RUN apt-get -y install nodejs npm postgresql-client

WORKDIR /nayduck/frontend

RUN npm install

RUN npm run build

WORKDIR /nayduck

CMD ["python3", "-m", "backend.backend"]