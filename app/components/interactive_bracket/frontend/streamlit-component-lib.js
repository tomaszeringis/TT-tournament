(function() {
  "use strict";

  /**
   * Minimal Streamlit Component Library for static HTML components.
   */
  var Streamlit = {
    /**
     * Set the component's value.
     */
    setComponentValue: function(value) {
      this.sendMsg("streamlit:setComponentValue", {value: value});
    },

    /**
     * Set the component's height.
     */
    setFrameHeight: function(height) {
      this.sendMsg("streamlit:setFrameHeight", {height: height});
    },

    /**
     * Tell Streamlit that the component is ready.
     */
    setComponentReady: function() {
      this.sendMsg("streamlit:componentReady", {apiVersion: 1});
    },

    /**
     * Event types.
     */
    RENDER_EVENT: "streamlit:render",

    /**
     * Event management.
     */
    events: {
      addEventListener: function(type, callback) {
        window.addEventListener("message", function(event) {
          if (event.data.type === type) {
            callback(event);
          }
        });
      }
    },

    /**
     * Send a message to the parent Streamlit app.
     */
    sendMsg: function(type, data) {
      var msg = Object.assign({
        isStreamlitMessage: true,
        type: type
      }, data);
      window.parent.postMessage(msg, "*");
    }
  };

  window.Streamlit = Streamlit;
})();
