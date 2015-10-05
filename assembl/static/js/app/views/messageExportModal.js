var Backbone = require('../shims/backbone.js'),
    Marionette = require('../shims/marionette.js'),
    i18n = require('../utils/i18n.js')
$ = require('../shims/jquery.js'),
_ = require('../shims/underscore.js'),
Promise = require('bluebird'),
FacebookViews = require('./facebookViews.js');

var Modal = Backbone.Modal.extend({
  template: '#tmpl-loader',
  className: 'group-modal popin-wrapper',
  cancelEl: '.js_close',
  keyControl: false,
  initialize: function(options) {
      console.log('initializing Modal');
      this.$('.bbm-modal').addClass('popin');
      this.$('.js_export_error_message').empty(); //Clear any error message that may have been put there
      this.messageCreator = null;
      this.exportedMessage = options.exportedMessage;
      this.formType = undefined; 
      this.currentView = undefined;

      var that = this;
      this.exportedMessage.getCreatorPromise().then(function(user) {
        that.messageCreator = user;
        that.template = '#tmpl-exportPostModal';
        that.render();
      });
    },
  events: {
      'change .js_export_supportedList': 'generateView'
    },
  serializeData: function() {
      if (this.messageCreator) {
        return {
          creator: this.messageCreator.get('name')
        }
      }
    },
  loadFbView: function(token) {
      var fbView = new FacebookViews.init({
        exportedMessage: this.exportedMessage,
        token: token
      });

      this.$('.js_source-specific-form').html(fbView.render().el);
      //Because we are not yet using marionette's version of Backbone.modal.
      fbView.onShow();
    },
  generateView: function(event) {
      //Whilst checking for accessTokens, make the region where
      //facebook will be rendered a loader

      var value = this.$(event.currentTarget)
                      .find('option:selected')
                      .val();

      this.formType = value;

      console.log('Generating the view', value);

      switch (value){
        case 'facebook':
          this.loadFbView();
          break;

        default:
          this.$('.js_source-specific-form').empty();
          this.$('.js_export_error_message').empty();
          this.currentView = null;
          break;
      }
    }
});

module.exports = Modal
