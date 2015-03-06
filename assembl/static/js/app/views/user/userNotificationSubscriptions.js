'use strict';

define(['backbone.marionette','app', 'jquery', 'underscore', 'common/collectionManager', 'common/context', 'models/notificationSubscription', 'models/roles', 'utils/i18n', 'utils/roles', 'models/emailAccounts'],
    function (Marionette, Assembl, $, _, CollectionManager, Ctx, NotificationSubscription, RolesModel, i18n, Roles, emailAccounts) {

        /**
         * User notification
         * */
        var Notification = Marionette.ItemView.extend({
            template:'#tmpl-userSubscriptions',
            tagName:'label',
            className:'checkbox dispb',
            initialize: function(options){
              var that = this;
              this.listenTo(Assembl.vent, 'notifications:refresh', function(role){
                 this.role = role;
                 that.render();
              });

              if(this.model === 'undefined'){
                this.template = "#tmpl-loader";
              }

              this.role = options.role;
            },
            ui: {
              currentSubscribeCheckbox: ".js_userNotification"
            },
            events: {
              'click @ui.currentSubscribeCheckbox': 'userNotification'
            },
            serializeData: function () {
                return {
                    subscription: this.model,
                    role: this.role,
                    i18n: i18n
                }
            },
            userNotification: function (e) {
                var elm = $(e.target);
                var status = elm.is(':checked') ? 'ACTIVE' : 'UNSUBSCRIBED';

                this.model.set("status", status);
                this.model.save(null, {
                    success: function (model, resp) {
                    },
                    error: function (model, resp) {
                        console.error('ERROR: userNotification', resp)
                    }
                });
            }
        });

        var Notifications = Marionette.CollectionView.extend({
            childView: Notification,
            initialize: function(options){
               this.collection = options.notificationsUser;
               this.childViewOptions = {
                 role: options.role
               }
            },
            collectionEvents: {
              'reset': 'render'
            }
        });

        /**
         * Notification template
         * */
        var TemplateSubscription = Marionette.ItemView.extend({
            template: '#tmpl-templateSubscription',
            tagName:'label',
            className:'checkbox dispb',
            initialize: function(options){
              var that = this;
              this.listenTo(Assembl.vent, 'notifications:refresh', function(role){
                that.roles = role;
                that.render();
              });

              this.roles = options.roles;
              this.notificationsUser = options.notificationsUser;
              this.notificationTemplates = options.notificationTemplates;
            },
            ui: {
              newSubscribeCheckbox: ".js_userNewNotification"
            },
            events: {
              'click @ui.newSubscribeCheckbox': 'userNewSubscription'
            },
            serializeData: function () {
              return {
                subscription: this.model,
                roles: this.roles,
                i18n: i18n
              }
            },
            userNewSubscription: function (e) {
                var elm = $(e.target),
                    that = this,
                    status = elm.is(':checked') ? 'ACTIVE' : 'UNSUBSCRIBED';

                var notificationSubscriptionTemplateModel = this.notificationTemplates.get(elm.attr('id'));

                var notificationSubscriptionModel = new NotificationSubscription.Model({
                        creation_origin: "USER_REQUESTED",
                        status: status,
                        '@type': notificationSubscriptionTemplateModel.get('@type'),
                        discussion: notificationSubscriptionTemplateModel.get('discussion'),
                        human_readable_description: notificationSubscriptionTemplateModel.get('human_readable_description')
                    });

                this.notificationsUser.add(notificationSubscriptionModel);

                notificationSubscriptionModel.save(null, {
                    success: function(model, response, options) {
                        that.notificationTemplates.remove(notificationSubscriptionTemplateModel);
                    },
                    error: function (model, resp) {
                        that.notificationsUser.remove(notificationSubscriptionModel);
                        console.error('ERROR: userNewSubscription', resp)
                    }
                })
            }

        });

        var TemplateSubscriptions = Marionette.CollectionView.extend({
            childView: TemplateSubscription,
            initialize: function(options){
                var addableGlobalSubscriptions = new Backbone.Collection();

                options.notificationTemplates.each(function (template) {
                    var alreadyPresent = options.notificationsUser.find(function (subscription) {
                        if (subscription.get('@type') === template.get('@type')) {
                            return true;
                        }
                        else {
                            return false
                        }
                    });
                    if (alreadyPresent === undefined) {
                        addableGlobalSubscriptions.add(template)
                    }
                });

                this.collection = addableGlobalSubscriptions;
                //that._initialEvents();

                this.childViewOptions = {
                    roles: options.role,
                    notificationsUser: options.notificationsUser,
                    notificationTemplates: addableGlobalSubscriptions
                }

            },
            collectionEvents: {
              'reset': 'render'
            }
        });

        /**
         *  Choose an email to notify user
         * */
        var NotificationByEmail = Marionette.ItemView.extend({
            template: '#tmpl-notificationByEmail',
            tagName: 'label',
            className: 'radio',
            ui: {
              preferredEmail: '.js_preferred'
            },
            events: {
              'click @ui.preferredEmail': 'preferredEmail'
            },
            serializeData: function(){
                return {
                    account: this.model
                }
            },
            preferredEmail: function(){

                var preferred = (this.$('input[name="email_account"]:checked').val()) ? true : false;

                this.model.set({preferred: preferred});

                this.model.save(null, {
                    success: function(){

                        console.debug('success');
                    },
                    error: function(){
                        console.debug('error');
                    }
                })

            }

        });

        var NotificationByEmails = Marionette.CompositeView.extend({
            template: '#tmpl-notificationByEmails',
            childView: NotificationByEmail,
            childViewContainer:'.controls'
        })


        /**
         * Subscripbe / Unsubscribe action
         * */
        var Subscriber = Marionette.ItemView.extend({
            template:'#tmpl-userSubscriber',
            ui: {
                unSubscription: ".js_unSubscription",
                subscription: ".js_subscription",
                btnSubscription:'.btnSubscription',
                btnUnsubscription:'.btnUnsubscription'
            },
            events: {
                'click @ui.unSubscription': 'unSubscription',
                'click @ui.subscription': 'subscription'
            },
            initialize: function(){
                this.listenTo(this, 'Subscriber:refresh', this.render);
            },
            serializeData: function(){
                return {
                    role: this.model
                }
            },

            unSubscription: function () {
                var that = this;

                if (this.model !== undefined) {
                    this.model.destroy({
                        success: function (model, resp) {
                            that.model = undefined;
                            that.trigger('Subscriber:refresh');

                            Assembl.vent.trigger('navBarRight:refresh', undefined);
                            Assembl.vent.trigger('notifications:refresh', undefined);
                            Assembl.vent.trigger('templateSubscriptions:refresh', undefined);
                        },
                        error: function (model, resp) {
                            console.error('ERROR: unSubscription failed', resp);
                        }});
                }
            },

            subscription: function(){
                var that = this;

                if (Ctx.getDiscussionId() && Ctx.getCurrentUserId()) {

                    var LocalRolesUser = new RolesModel.Model({
                        role: Roles.PARTICIPANT,
                        discussion: 'local:Discussion/' + Ctx.getDiscussionId(),
                        user_id: Ctx.getCurrentUserId()
                    });

                    LocalRolesUser.save(null, {
                        success: function (model, resp) {
                            that.model = LocalRolesUser;
                            that.trigger('Subscriber:refresh');

                            Assembl.vent.trigger('navBarRight:refresh', model);
                            Assembl.vent.trigger('notifications:refresh', model);
                            Assembl.vent.trigger('templateSubscriptions:refresh', model);
                        },
                        error: function (model, resp) {
                            console.error('ERROR: joinDiscussion->subscription', resp);
                        }
                    })
                }
            }

        });

        var userNotificationSubscriptions = Marionette.LayoutView.extend({
            template: '#tmpl-userNotificationSubscriptions',
            className: 'admin-notifications',
            regions: {
              userNotifications:'#userNotifications',
              templateSubscription: '#templateSubscriptions',
              userSubscriber: '#subscriber',
              notifByEmail: '#notifByEmail'
            },
            onBeforeShow: function () {
                var that = this,
                    collectionManager = new CollectionManager();

                $.when(collectionManager.getNotificationsUserCollectionPromise(),
                       collectionManager.getNotificationsDiscussionCollectionPromise(),
                       collectionManager.getLocalRoleCollectionPromise())
                    .then(function (NotificationsUser, notificationTemplates, allRoles) {

                        var role =  allRoles.find(function (local_role) {
                                return local_role.get('role') === Roles.PARTICIPANT;
                            });
                        var subscriber = new Subscriber({
                            model: role
                        });
                        that.getRegion('userSubscriber').show(subscriber);

                        var templateSubscriptions = new TemplateSubscriptions({
                            notificationTemplates: notificationTemplates,
                            notificationsUser: NotificationsUser,
                            role: role
                        });
                        that.getRegion('templateSubscription').show(templateSubscriptions);

                        var userNotification = new Notifications({
                            notificationsUser: NotificationsUser,
                            role: role
                        });
                        that.getRegion('userNotifications').show(userNotification);

                    });

               var emailAccount = new emailAccounts.Collection();
               var notificationByEmails = new NotificationByEmails({
                   collection: emailAccount
               });
               emailAccount.fetch();

               this.notifByEmail.show(notificationByEmails);
            },

            serializeData: function () {
                return {
                    i18n: i18n
                }
            }

        });

        return userNotificationSubscriptions;
    });