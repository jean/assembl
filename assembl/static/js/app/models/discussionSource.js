'use strict';
/**
 * 
 * @module app.models.discussionSource
 */

var Base = require('./base.js'),
    Ctx = require('../common/context.js'),
    $ = require('jquery');

/**
 * Represents a discussion's message source
 * Frontend model for :py:class:`assembl.models.generic.ContentSource`
 * @class app.models.discussionSource.sourceModel
 * @extends app.models.Base.Model
 */
var sourceModel = Base.Model.extend({
  constructor: function sourceModel() {
    Base.Model.apply(this, arguments);
  },

  urlRoot: Ctx.getApiV2DiscussionUrl() + 'sources',
  defaults: {
    'name': '',
    'admin_sender': '',
    'post_email_address': '',
    'creation_date': '',
    'host': '',
    'discussion_id': '',
    '@type': '',
    'folder': '',
    'use_ssl': false,
    'port': 0
  },
  validate: function(attrs, options) {
    /**
     * check typeof variable
     * */
     
  },
  doReimport: function() {
    var url = this.url() + '/fetch_posts';
    return $.post(url, {reimport: true});
  },
  doReprocess: function() {
    var url = this.url() + '/fetch_posts';
    return $.post(url, {reprocess: true});
  }

});

var sourceCollection = Base.Collection.extend({
  constructor: function sourceCollection() {
    Base.Collection.apply(this, arguments);
  },

  url: Ctx.getApiV2DiscussionUrl() + 'sources',
  model: sourceModel
});

module.exports = {
  Model: sourceModel,
  Collection: sourceCollection
};

