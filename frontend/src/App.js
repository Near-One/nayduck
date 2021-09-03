import React, { createContext, useReducer }  from 'react';
import { Route, BrowserRouter as Router, Switch } from "react-router-dom";

import Login from "./Login";
import Home from "./Home";
import * as reducer from "./reducer";


export const AuthContext = createContext();


function App() {
  const [state, dispatch] = useReducer(reducer.reducer, reducer.initialState);

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
