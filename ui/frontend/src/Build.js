import React, { useState, useEffect } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common";


function Build (props) {
    const [BuildInfo, setBuildInfo] = useState([]);

    useEffect(() => {
        common.fetchAPI('/build/' + (0 | props.match.params.build_id))
            .then(data => setBuildInfo(data));
    }, [props.match.params.build_id]);

    return (
      <div>
        <table style={{"border" : "0px", "width": "40%"}}> <tbody>
          <tr><td style={{"border": "0px"}}><NavLink to={"/"}> Back To All Runs</NavLink></td></tr>
        </tbody></table>
        <br/><br/>

        <table className="big"><tbody>
            <tr><td style={{"width":"20%"}}>Commit</td><td>
             {BuildInfo.branch} (<a href={common.GitRepo()+"/commit/"+BuildInfo.sha}>{BuildInfo.sha}</a>)<br/>
            {BuildInfo.title}<br/>
             requested by {BuildInfo.requester}
            </td></tr>
            <tr><td>Status</td><td style={{"color": common.StatusColor(BuildInfo.status)}}>{BuildInfo.status}</td></tr>
            <tr><td>Build Time</td><td>{BuildInfo.build_time}</td></tr>
            <tr><td>Finished</td><td>{BuildInfo.finished}</td></tr>
            <tr><td>Started</td><td>{BuildInfo.started}</td></tr>
            <tr><td style={{"width":"20%"}}>stderr</td><td><textarea style={{"width":"100%", "height": "300px"}} value={BuildInfo.stderr}>{BuildInfo.stderr}</textarea></td></tr>
            <tr><td style={{"width":"20%"}}>stdout</td><td><textarea style={{"width":"100%", "height": "300px"}} value={BuildInfo.stdout}>{BuildInfo.stdout}</textarea></td></tr>

        </tbody></table>

      </div>
    );
}

export default Build;
