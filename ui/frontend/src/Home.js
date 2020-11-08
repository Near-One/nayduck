import React, { useContext } from "react";
import { Redirect,
    Route,
    HashRouter } from "react-router-dom";
import { AuthContext } from "./App";
import ARun from "./a_run";
import AllRuns from "./all_runs";
import ATest from "./a_test";
import TestHistory from "./test_history";
import Build from "./Build";
  
export default function Home() {
  const { state, dispatch } = useContext(AuthContext);

  if (!state.isLoggedIn) {
    return <Redirect to="/login" />;
  }

  const handleLogout = () => {
    dispatch({
      type: "LOGOUT"
    });
  } 
  return (
      <div className="container">
        <button class="logout" onClick={()=> handleLogout()}>Logout</button>
      <HashRouter>
        <div className="content">
            <Route exact path="/" component={AllRuns}/>
            <Route path="/run/:run_id" component={ARun}/>
            <Route path="/test/:test_id" component={ATest}/>
            <Route path="/test_history/:test_id" component={TestHistory}/>
            <Route path="/build/:build_id" component={Build}/>
        </div>
      </HashRouter>
  </div>
  );
};
