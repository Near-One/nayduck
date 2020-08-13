import React from "react";
import {
    NavLink,
  } from "react-router-dom";


export function StatusColor(status) {
    switch (status) {
    case "FAILED" || "BUILD FAILED":   return "red";
    case "PASSED":   return "green";
    case "RUNNING":   return "blue";
    case "OTHER":   return "grey";
    default:      return "black";
    }
}


export function HistorySwitchText(status, count) {
    switch (status) {
        case "FAILED" :   return "F:"+count;
        case "PASSED":   return "P:"+count;
        case "OTHER":   return "O:"+count;
        default:      return "";
        }
}

export function RenderHistory(a_run, title) {
    return ( 
        <NavLink to={"/test_history/" + a_run.test_id}>{title}<table style = {{"border": "0px"}}><tbody><tr>
            {Object.entries(a_run.history).map( ([key, value]) => 
                <td style={{"border": "0px",
                            "padding": "0px",
                            "fontSize": "10px",
                            "color": StatusColor(key)}}>
                    {HistorySwitchText(key, value)}</td>
            )}
            </tr></tbody></table></NavLink>
        )
}

export function ServerIp() {
    return process.env.REACT_APP_SERVER_IP
}

export function GitRepo() {
    return process.env.REACT_APP_GIT_REPO
}

