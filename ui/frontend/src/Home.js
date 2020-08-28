import React, { useContext } from "react";
import { Redirect,
    Route,
    HashRouter } from "react-router-dom";
import { AuthContext } from "./App";
import ARun from "./a_run";
import AllRuns from "./all_runs";
import ATest from "./a_test";
import TestHistory from "./test_history";
  


export default function Home() {
  const { state, dispatch } = useContext(AuthContext);

  if (!state.isLoggedIn) {
    return <Redirect to="/login" />;
  }

  const { organizations_url } = state.user

  const handleLogout = () => {
    dispatch({
      type: "LOGOUT"
    });
  } 
  fetch(//"https://api.github.com/users/abacabadabacaba/orgs", {
      organizations_url, {
  })
    .then(response => response.json())
    .then(data => {
     for (var d of data) {
        if (d["login"] == "nearprotocol") {
            console.log("Welcome to Nay!");
        }
     }
    });
  return (
      <div className="container">
        <button class="logout" onClick={()=> handleLogout()}>Logout</button>
      <HashRouter>
        <div className="content">
            <Route exact path="/" component={AllRuns}/>
            <Route path="/run/:run_id" component={ARun}/>
            <Route path="/test/:test_id" component={ATest}/>
            <Route path="/test_history/:test_id" component={TestHistory}/>
        </div>
      </HashRouter>
  </div>
  );
};
