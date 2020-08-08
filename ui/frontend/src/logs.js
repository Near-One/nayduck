import React , { useEffect  } from "react";
import {
    NavLink,
    HashRouter,
    Route
  } from "react-router-dom";

function Logs (props) {
   
    useEffect(() => {
        console.log(props);
        fetch('http://localhost:5000/log', {
          headers : { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
           },
           method: 'POST',
           body: JSON.stringify({'test_id': props.match.params.test_id, 'type': props.match.params.type}),
          }).then((response) => response.json())
          .then(data => {
          
        });
    }, []);

    return (
      <div>
          
      </div>
    );
}
 
export default Logs;