import React, { useState, useEffect, useContext } from "react";
import { Redirect } from "react-router-dom";

import { AuthContext } from "./App";
import { ServerIp }  from "./common"


 export default function LocalAuthConfirmed() {
  const { state, dispatch } = useContext(AuthContext);
  
  const [member, setMember] = useState(false);
  const [code, setCode] = useState();

  const { user } = state
  useEffect(() => {
    fetch(
      "https://api.github.com/users/skidanovalex/orgs", {
      //user.organizations_url, {  
      headers: new Headers({
        'Authorization': 'token '+ user.token, 
      }),
    })
      .then(response => response.json())
      .then(data => {
      console.log(data);
      for (var d of data) {
          if (d["login"] === "nearprotocol") {
              console.log("Welcome to Nay!");
              setMember(true);
              fetch(ServerIp() + '/get_auth_code', {
                headers : { 
                  'Content-Type': 'application/json',
                  'Accept': 'application/json'
                },
                method: 'POST',
                body: JSON.stringify({'github_login': user.login}),
                }).then((response) => response.json())
                .then(data => {
                  setCode(data["code"]);
              })
              .catch(function(err) {
                console.log('Fetch Error :-S', err);
              });
              break;
          }
          console.log("Break")
      }
      }).catch(error => {
        console.log(error);
      });
    }, []);

    const handleLogout = () => {
      dispatch({
        type: "LOGOUT"
      });
    } 

    if (!state.isLoggedIn) {
      return <Redirect to="/login" />;
    }

    return (
        <div className="container">
          <button class="logout" onClick={()=> handleLogout()}>Logout</button>
          <div style={{"height": "20vh"}} className="section-login">
            {member ? "The code: " + code : user.login + " are not a member of NearProtocol Org."}
          </div>
        </div>
    );

}
