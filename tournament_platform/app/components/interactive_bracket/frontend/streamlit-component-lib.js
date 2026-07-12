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
     *
     * The official streamlit-component-lib dispatches a CustomEvent whose
     * payload lives on `event.detail`. Consumers (index.html) therefore read
     * `event.detail.args` / `event.detail.theme`. This shim receives raw
     * postMessage MessageEvents where the payload lives on `event.data` and
     * `event.detail` is undefined. We MUST normalize to `{ detail: <payload> }`
     * so the render handler doesn't throw `Cannot read properties of undefined`
     * before it can size the iframe (which previously left the bracket blank).
     */
    events: {
      addEventListener: function(type, callback) {
        window.addEventListener("message", function(event) {
          if (event.data && event.data.type === type) {
            callback({ detail: event.data });
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
