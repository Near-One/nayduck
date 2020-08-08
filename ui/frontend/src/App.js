import React from 'react';
import {
  Route,
  HashRouter
} from "react-router-dom";
import ARun from "./a_run";
import AllRuns from "./all_runs";
import ATest from "./a_test";
import TestHistory from "./test_history";

import './App.css';

function App() {
  

  return ( 
  <HashRouter>
  <div className="content">
    <Route exact path="/" component={AllRuns}/>
    <Route path="/run/:run_id" component={ARun}/>
    <Route path="/test/:test_id" component={ATest}/>
    <Route path="/test_history/:test_id" component={TestHistory}/>
  </div>
  </HashRouter>);
}

App.use(cors())
export default App;
