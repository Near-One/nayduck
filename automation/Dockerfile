FROM ubuntu:latest

ENV TZ=Etc/UTC

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN mkdir /.nayduck

RUN mkdir /datadrive

RUN apt-get update

RUN apt-get -y install fdisk git python3-pip libpq-dev lld libclang-dev curl

RUN git clone -b docker https://github.com/near/nayduck.git

RUN pip install -r nayduck/requirements.txt 

RUN apt-get -y install nodejs npm postgresql-client

WORKDIR /nayduck/frontend

RUN npm install

RUN npm run build

RUN apt install -y git binutils-dev libcurl4-openssl-dev zlib1g-dev libdw-dev libiberty-dev cmake gcc g++ docker.io protobuf-compiler libssl-dev pkg-config clang llvm awscli

RUN curl https://sh.rustup.rs -sSf > /tmp/rust.sh && sh /tmp/rust.sh -y

WORKDIR /nayduck
