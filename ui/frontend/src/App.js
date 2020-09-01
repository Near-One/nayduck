import React, { createContext, useReducer }  from 'react';
import {
  Route,
  BrowserRouter as Router, 
  Switch
} from "react-router-dom";
import Login from "./Login";
import LocalAuth from "./LocalAuth";
import LocalAuthConfirmed from "./LocalAuthConfirmed";
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
        <Route path="/local_auth" component={LocalAuth}/>
        <Route path="/local_auth_confirmed" component={LocalAuthConfirmed}/>
        <Route path="/" component={Home}/>
        
      </Switch>
    </Router>
    </AuthContext.Provider>
  );
}

export default App;
