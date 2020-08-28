import React, { createContext, useReducer }  from 'react';
import {
  Route,
  HashRouter,
  BrowserRouter as Router, 
  Switch
} from "react-router-dom";
import ARun from "./a_run";
import AllRuns from "./all_runs";
import ATest from "./a_test";
import TestHistory from "./test_history";
import Login from "./Login";
import Home from "./Home";
import { initialState, reducer } from "./reducer";


import './App.css';

export const AuthContext = createContext();


function App() {
  const [state, dispatch] = useReducer(reducer, initialState);

  

  return ( 
<AuthContext.Provider
      value={{
        state,
        dispatch
      }}
    >
    <Router>
      <Switch>
        <Route path="/login" component={Login}/>
        <Route path="/" component={Home}/>
      </Switch>
    </Router>
    </AuthContext.Provider>
  );
}

export default App;
