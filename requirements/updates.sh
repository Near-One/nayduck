set -x
echo -ne '\n' | sudo apt update -y
echo -ne '\n' | sudo apt install python3.7
echo -ne '\n' | sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.6 1
echo -ne '\n' | sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.7 2
echo -ne '\n' | sudo update-alternatives --config python3
echo -ne '\n' | sudo apt-get install --reinstall python3-apt
echo -ne '\n' | sudo apt-get install nodejs
echo -ne '\n' | sudo apt-get install npm
echo -ne '\n' | sudo npm install -g npx
echo -ne '\n' | npm install --save react-router-dom
echo -ne '\n' | sudo apt-get install python3-dev
echo -ne '\n' | sudo apt install libpython3.7-dev
curl https://sh.rustup.rs -sSf > c
sh c -y
echo -ne '\n' | source $HOME/.cargo/env
echo -ne '\n' | $HOME/.cargo/bin/rustup target add wasm32-unknown-unknown
echo -ne '\n' | sudo apt-get install clang
echo -ne '\n' | sudo apt-get install cmake
echo -ne '\n' | sudo update-alternatives --install /usr/bin/python python /usr/bin/python2.7 1
echo -ne '\n' | sudo update-alternatives --install /usr/bin/python python /usr/bin/python3.7 2
echo -ne '\n' | sudo update-alternatives --config python
echo -ne '\n' | sudo apt-get -y install python3-pip
