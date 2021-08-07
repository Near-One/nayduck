import React, { useState, useEffect } from "react";
import { NavLink } from "react-router-dom";

import * as common from "./common";


function Build (props) {
    const [BuildInfo, setBuildInfo] = useState([]);

    useEffect(() => {
        common.fetchAPI('/build/' + (0 | props.match.params.build_id))
            .then(data => setBuildInfo(data));
    }, [props.match.params.build_id]);

    const timeStats = common.formatTimeStats(BuildInfo);

    return (
      <div>
        <table style={{"border" : "0px", "width": "40%"}}> <tbody>
          <tr><td style={{"border": "0px"}}><NavLink to={"/"}> Back To All Runs</NavLink></td></tr>
        </tbody></table>
        <br/><br/>

        <table className="big"><tbody>
            <tr>
                <td>Commit</td>
                <td>{common.commitLink(BuildInfo)} {BuildInfo.title}</td>
             </tr>
            <tr><td>Requested by</td><td>{BuildInfo.requester}</td></tr>
            <tr><td>Status</td><td style={{"color": common.StatusColor(BuildInfo.status)}}>{BuildInfo.status}</td></tr>
            <tr><td>Build Time</td><td>{timeStats.delta}</td></tr>
            <tr><td>Finished</td><td>{timeStats.finished}</td></tr>
            <tr><td>Started</td><td>{timeStats.started}</td></tr>
            <tr><td>stderr</td><td><textarea style={{"width":"100%", "height": "300px"}} value={BuildInfo.stderr}>{BuildInfo.stderr}</textarea></td></tr>
            <tr><td>stdout</td><td><textarea style={{"width":"100%", "height": "300px"}} value={BuildInfo.stdout}>{BuildInfo.stdout}</textarea></td></tr>
        </tbody></table>

      </div>
    );
}

export default Build;
