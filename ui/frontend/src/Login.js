import React, { useState, useEffect, useContext } from "react";
import { Redirect } from "react-router-dom";
import Styled from "styled-components";
import GithubIcon from "mdi-react/GithubIcon";
import { AuthContext } from "./App";


export default function Login() {
  const { state, dispatch } = useContext(AuthContext);
  const [data, setData] = useState({ errorMessage: "", isLoading: false });

  const { client_id, redirect_uri } = state;

  useEffect(() => {
    // After requesting Github access, Github redirects back to your app with a code parameter
    const url = window.location.href;
    const hasCode = url.includes("?code=");

    // If Github API returns the code parameter
    if (hasCode) {
      const newUrl = url.split("?code=");
      window.history.pushState({}, null, newUrl[0]);
      setData({ ...data, isLoading: true });

      const requestData = {
        client_id: state.client_id,
        redirect_uri: state.redirect_uri,
        client_secret: state.client_secret,
        code: newUrl[1]
      };

      const proxy_url = state.proxy_url;

      // Use code parameter and other parameters to make POST request to proxy_server
      fetch(proxy_url, {
        method: "POST",
        body: JSON.stringify(requestData)
      })
        .then(response => response.json())
        .then(data => {
         console.log(data);
          dispatch({
            type: "LOGIN",
            payload: { user: data, isLoggedIn: true }
          });
        })
        .catch(error => {
          setData({
            isLoading: false,
            errorMessage: "Sorry! Login failed"
          });
        });
    }
  }, [state, dispatch, data]);

  if (state.isLoggedIn) {
    return <Redirect to="/" />;
  }

  return (
    <Wrapper>
      <section className="container">
        <div>
          <img src="duck.jpg"/>
          <span>{data.errorMessage}</span>
          <div className="login-container">
            {data.isLoading ? (
              <div className="loader-container">
                <div className="loader"></div>
              </div>
            ) : (
                <a
                  className="login-link"
                  href={`https://github.com/login/oauth/authorize?scope=read:user&client_id=${client_id}&redirect_uri=${redirect_uri}`}
                  onClick={() => {
                    setData({ ...data, errorMessage: "" });
                  }}
                >
                  <GithubIcon />
                  <span>Login with GitHub</span>
                </a>
            )}
          </div>
        </div>
      </section>
    </Wrapper>
  );
}

const Wrapper = Styled.section`
  .container {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    font-family: Arial;
    
    > div:nth-child(1) {
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      box-shadow: 0 1px 4px 0 rgba(0, 0, 0, 0.2);
      transition: 0.3s;
      width: 25%;
      height: 45%;
     
      .login-container {
        background-color: #000;
        border-radius: 3px;
        color: #fff;
        display: flex;
        align-items: center;
        justify-content: center;
        > .login-link {
          text-decoration: none;
          color: #fff;
          text-transform: uppercase;
          cursor: default;
          display: flex;
          align-items: center;          
          height: 40px;
          > span:nth-child(2) {
            margin-left: 5px;
          }
        }
        .loader-container {
          display: flex;
          justify-content: center;
          align-items: center;          
          height: 40px;
        }
        .loader {
          border: 4px solid #f3f3f3;
          border-top: 4px solid #3498db;
          border-radius: 50%;
          width: 12px;
          height: 12px;
          animation: spin 2s linear infinite;
        }
        @keyframes spin {
          0% {
            transform: rotate(0deg);
          }
          100% {
            transform: rotate(360deg);
          }
        }
      }
    }
  }
`;
