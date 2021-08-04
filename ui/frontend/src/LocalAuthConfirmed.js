import React, { useState, useEffect, useContext } from "react";
import { Redirect } from "react-router-dom";

import { AuthContext } from "./App";
import { fetchApi }  from "./common"


export default function LocalAuthConfirmed() {
    const { state, dispatch } = useContext(AuthContext);

    const [member, setMember] = useState(false);
    const [code, setCode] = useState();

    const { user } = state
    useEffect(() => {
        fetch('https://api.github.com/user/orgs', {})
            .then(response => response.json())
            .then(data => {
                console.log(data);
                for (var d of data) {
                    if (d["login"] === "nearprotocol" ||
                        d["login"] === "near") {
                        console.log("Welcome to Nay!");
                        setMember(true);
                        fetchApi('/get_auth_code/' + user.login)
                            .then(data => setCode(data["code"]));
                        break;
                    }
                }
            }).catch(error => console.log(error));
    }, [user]);

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
