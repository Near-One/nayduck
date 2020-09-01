import React, { useState, useEffect, useContext } from "react";
import { Redirect } from "react-router-dom";
import { AuthContext } from "./App";
import { LoginPage }  from "./common"


export default function LocalAuth() {
  const { state, dispatch } = useContext(AuthContext);
  const [data, setData] = useState({ errorMessage: "", isLoading: false });

  const { client_id_local, redirect_uri_local } = state;

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
        client_id: state.client_id_local,
        redirect_uri: state.redirect_uri_local,
        client_secret: state.client_secret_local,
        code: newUrl[1]
      };
      console.log(requestData)

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
    return <Redirect to="/local_auth_confirmed" />;
  }

  return LoginPage(client_id_local, redirect_uri_local, data, setData)
}
