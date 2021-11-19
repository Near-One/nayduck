import React, { createContext, useState } from 'react';
import { HashRouter, Route } from "react-router-dom";

import ARun from "./a_run";
import ATest from "./a_test";
import AllRuns from "./all_runs";
import NightlyStats from "./nightly_stats";
import Build from "./Build";
import * as Login from "./Login";
import TestHistory from "./test_history";


export const AuthContext = createContext();


function App() {
    const [authState, setAuthState] = useState(Login.getLoginState());
    return <AuthContext.Provider value={[authState, setAuthState]}>
        <Login.LoginBar/>
        <HashRouter>
            <Route path="/" exact component={AllRuns}/>
            <Route path="/run/:run_id" component={ARun}/>
            <Route path="/test/:test_id" component={ATest}/>
            <Route path="/test_history/:test_id" component={TestHistory}/>
            <Route path="/build/:build_id" component={Build}/>
            <Route path="/stats/" component={NightlyStats}/>
        </HashRouter>
    </AuthContext.Provider>;
}


export default App;
