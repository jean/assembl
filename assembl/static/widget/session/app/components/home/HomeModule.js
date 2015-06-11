'use strict';

var HomeModule = angular.module('HomeModule', ['ui.router']);

HomeModule.config(['$stateProvider', function($stateProvider) {
    $stateProvider
        .state('session.home',{
            url: '/home?config',
            templateUrl: 'app/components/home/HomeView.html',
            controller: 'HomeController',
            resolve: {
                config: ['WidgetService','$stateParams', function(WidgetService, $stateParams){
                    if($stateParams.config){
                        var id = decodeURIComponent($stateParams.config).split('/')[1];
                        return WidgetService.get({id: id}).$promise;
                    }
                }]
            }
        });
}]);