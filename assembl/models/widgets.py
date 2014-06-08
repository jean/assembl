from itertools import chain

from sqlalchemy import (
    Column, Integer, ForeignKey, Text, String, inspect)
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.associationproxy import association_proxy
import simplejson as json
import uuid

from ..auth import (
    CrudPermissions, P_ADD_IDEA, P_READ, P_EDIT_IDEA)
from . import DiscussionBoundBase
from .synthesis import (
    Discussion, ExplicitSubGraphView, SubGraphIdeaAssociation, Idea,
    IdeaContentWidgetLink, IdeaLink)
from .generic import Content
from .post import IdeaProposalPost
from ..auth import P_ADD_POST, P_ADMIN_DISC, Everyone, CrudPermissions
from .auth import User
from ..views.traversal import CollectionDefinition
from ..semantic.virtuoso_mapping import QuadMapPatternS
from ..semantic.namespaces import (ASSEMBL, QUADNAMES)


class Widget(DiscussionBoundBase):
    __tablename__ = "widget"

    id = Column(Integer, primary_key=True)

    type = Column(String(60), nullable=False)

    __mapper_args__ = {
        'polymorphic_identity': 'widget',
        'polymorphic_on': 'type',
        'with_polymorphic': '*'
    }

    settings = Column(Text)  # JSON blob
    state = Column(Text)  # JSON blob

    discussion_id = Column(
        Integer,
        ForeignKey('discussion.id', ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False
    )
    discussion = relationship(Discussion, backref="widgets")

    def get_discussion_id(self):
        return self.discussion_id

    @classmethod
    def get_discussion_condition(cls, discussion_id):
        return cls.discussion_id == discussion_id

    def get_user_states_uri(self):
        return 'local:Widget/%d/user_states' % (self.id,)

    # Eventually: Use extra_columns to get WidgetUserConfig
    # through user_id instead of widget_user_config.id

    @property
    def settings_json(self):
        if self.settings:
            return json.loads(self.settings)
        return {}

    @settings_json.setter
    def settings_json(self, val):
        self.settings = json.dumps(val)

    @property
    def state_json(self):
        if self.state:
            return json.loads(self.state)
        return {}

    @state_json.setter
    def state_json(self, val):
        self.state = json.dumps(val)

    def get_user_state(self, user_id):
        state = self.db.query(WidgetUserConfig).filter_by(
            widget=self, user_id=user_id).first()
        if state:
            return state.state_json

    def get_all_user_states(self):
        return [c.state_json for c in self.user_configs]

    def set_user_state(self, user_state, user_id):
        state = self.db.query(WidgetUserConfig).filter_by(
            widget=self, user_id=user_id).first()
        if not state:
            state = WidgetUserConfig(widget=self, user_id=user_id)
            self.db.add(state)
        state.state_json = user_state

    def update_json(self, json, user_id=Everyone):
        from ..auth.util import user_has_permission
        if user_has_permission(self.discussion_id, user_id, P_ADMIN_DISC):
            new_type = json.get('@type', self.type)
            if self.type != new_type:
                polymap = inspect(self.__class__).polymorphic_identity
                if new_type not in polymap:
                    return None
                new_type = polymap[new_type].class_
                new_instance = self.change_class(new_type)
                return new_instance.update_json(json)
            if 'settings' in json:
                self.settings_json = json['settings']
            if 'discussion' in json:
                self.discussion = Discussion.get_instance(json['discussion'])
        if 'state' in json:
            self.state_json = json['state']
        if user_id and user_id != Everyone and 'user_state' in json:
            self.set_user_state(json['user_state'], user_id)
        return self

    crud_permissions = CrudPermissions(P_ADMIN_DISC)


class BaseIdeaWidget(Widget):
    __mapper_args__ = {
        'polymorphic_identity': 'idea_view_widget',
    }

    @property
    def base_idea_id(self):
        if self.base_idea_link:
            return self.base_idea_link.idea_id

    @base_idea_id.setter
    def set_base_idea_id(self, id):
        if self.base_idea_link:
            self.base_idea_link.idea_id = id
        else:
            idea = Idea.get_instance(id)
            self.base_idea_link = BaseIdeaWidgetLink(widget=self, idea=idea)

    def get_ideas_uri(self):
        return 'local:Discussion/%d/widgets/%d/base_idea/-/children' % (
            self.discussion_id, self.id)

    def get_messages_uri(self):
        return 'local:Discussion/%d/widgets/%d/base_idea/-/widgetposts' % (
            self.discussion_id, self.id)

    @classmethod
    def extra_collections(cls):
        class BaseIdeaCollection(CollectionDefinition):
            def __init__(self):
                super(BaseIdeaCollection, self).__init__(
                    cls, cls.base_idea)

            def decorate_query(self, query, parent_instance):
                return query.join(BaseIdeaWidgetLink).join(
                    Widget).filter(Widget.id == parent_instance.id).filter(
                    Widget.idea_links.of_type(BaseIdeaWidgetLink))

        return {'base_idea': BaseIdeaCollection()}


class IdeaCreatingWidget(BaseIdeaWidget):
    __mapper_args__ = {
        'polymorphic_identity': 'idea_creating_widget',
    }

    def get_confirm_ideas_uri(self):
        idea_uri = self.settings_json.get('idea', None)
        if idea_uri:
            return ('local:Discussion/%d/widgets/%d/confirm_ideas') % (
                self.discussion_id, self.id)

    def get_confirm_messages_uri(self):
        idea_uri = self.settings_json.get('idea', None)
        if idea_uri:
            return ('local:Discussion/%d/widgets/%d/confirm_messages') % (
                self.discussion_id, self.id)

    def get_confirmed_ideas(self):
        # TODO : optimize
        return [idea.uri() for idea in self.generated_ideas if not idea.hidden]

    def set_confirmed_ideas(self, idea_ids):
        for idea in self.generated_ideas:
            uri = idea.uri()
            idea.hidden = (uri not in idea_ids)

    def get_confirmed_messages(self):
        root_idea_id = self.base_idea_id
        ids = self.db.query(Content.id).join(
            IdeaContentWidgetLink).join(Idea).join(
                IdeaLink, IdeaLink.target_id == Idea.id).filter(
                    IdeaLink.source_id == root_idea_id
                ).filter(~Content.hidden).all()
        return [Content.uri_generic(id) for (id,) in ids]

    def set_confirmed_messages(self, post_ids):
        root_idea_id = self.base_idea_id
        for post in self.db.query(Content).join(IdeaContentWidgetLink).join(
                Idea).join(IdeaLink, IdeaLink.target_id == Idea.id).filter(
                IdeaLink.source_id == root_idea_id).all():
            post.hidden = (post.uri() not in post_ids)

    def get_add_post_endpoint(self, idea):
        'local:Discussion/%d/widgets/%d/base_idea/-/children/%d/widgetposts' % (
            self.discussion_id, self.id, idea.id)

    @classmethod
    def extra_collections(cls):
        class BaseIdeaCollection(CollectionDefinition):
            def __init__(self):
                super(BaseIdeaCollection, self).__init__(
                    cls, cls.base_idea)

            def decorate_query(self, query, parent_instance):
                return query.join(BaseIdeaWidgetLink).join(
                    Widget).filter(Widget.id == parent_instance.id).filter(
                    Widget.idea_links.of_type(BaseIdeaWidgetLink))

            def decorate_instance(
                    self, instance, parent_instance, assocs, user_id):
                super(BaseIdeaCollection, self).decorate_instance(
                    instance, parent_instance, assocs, user_id)
                for inst in chain(assocs[:], (instance,)):
                    if isinstance(inst, Idea):
                        inst.hidden = True
                        post = IdeaProposalPost(
                            proposes_idea=inst, creator_id=user_id,
                            discussion_id=inst.discussion_id,
                            message_id=uuid.uuid1().urn,
                            body="", subject=inst.short_title)
                        assocs.append(post)
                        assocs.append(IdeaContentWidgetLink(
                            content=post, idea=inst.parents[0],
                            creator_id=user_id))
                        assocs.append(GeneratedIdeaWidgetLink(idea=inst))

        return {'base_idea': BaseIdeaCollection()}


class CreativityWidget(IdeaCreatingWidget):
    default_view = 'creativity_widget'
    __mapper_args__ = {
        'polymorphic_identity': 'creativity_session_widget',
    }


# These do not seem to be distinguished yet.
# class CardGameWidget(CreativityWidget):
#     __mapper_args__ = {
#         'polymorphic_identity': 'cardgame_widget',
#     }


# class JukeTubeWidget(CreativityWidget):
#     __mapper_args__ = {
#         'polymorphic_identity': 'juketube_widget',
#     }


class MultiCriterionVotingWidget(Widget):
    default_view = 'voting_widget'
    __mapper_args__ = {
        'polymorphic_identity': 'multicriterion_voting_widget',
    }

    def get_criteria_uri(self):
        idea_uri = self.settings_json.get('idea', None)
        if idea_uri:
            return 'local:Idea/%d/criteria' % (
                Idea.get_database_id(idea_uri),)

    def get_user_votes_uri(self):
        idea_uri = self.settings_json.get('idea', None)
        if idea_uri:
            return 'local:Idea/%d/votes' % (
                Idea.get_database_id(idea_uri),)

    def get_vote_results_uri(self):
        idea_uri = self.settings_json.get('idea', None)
        if idea_uri:
            return 'local:Idea/%d/vote_results' % (
                Idea.get_database_id(idea_uri),)

    @property
    def base_idea_id(self):
        return self.settings_json.get('idea', None)

    @property
    def base_idea(self):
        idea_id = self.base_idea_id
        if idea_id:
            return Idea.get_instance(idea_id)


class WidgetUserConfig(DiscussionBoundBase):
    __tablename__ = "widget_user_config"

    id = Column(Integer, primary_key=True)

    widget_id = Column(
        Integer,
        ForeignKey('widget.id',
                   ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False)
    widget = relationship(Widget, backref="user_configs")

    user_id = Column(
        Integer,
        ForeignKey('user.id',
                   ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False)
    user = relationship(User)

    state = Column('settings', Text)  # JSON blob

    @property
    def state_json(self):
        if self.state:
            return json.loads(self.state)
        return {}

    @state_json.setter
    def state_json(self, val):
        self.state = json.dumps(val)

    def get_discussion_id(self):
        return self.widget.discussion_id

    @classmethod
    def get_discussion_condition(cls, discussion_id):
        return (cls.widget_id == Widget.id) & (
            Widget.discussion_id == discussion_id)

    crud_permissions = CrudPermissions(P_ADD_POST)  # all participants...


class IdeaWidgetLink(DiscussionBoundBase):
    __tablename__ = 'idea_widget_link'

    id = Column(Integer, primary_key=True,
                info={'rdf': QuadMapPatternS(None, ASSEMBL.db_id)})
    type = Column(String(60))

    idea_id = Column(Integer, ForeignKey(Idea.id),
                     nullable=False, index=True)
    idea = relationship(Idea, backref="widget_links")

    widget_id = Column(Integer, ForeignKey(
        Widget.id, ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False, index=True)
    #widget = relationship(Widget, backref='idea_links')

    __mapper_args__ = {
        'polymorphic_identity': 'abstract_idea_widget_link',
        'polymorphic_on': type,
        'with_polymorphic': '*'
    }

    def get_discussion_id(self):
        if self.idea:
            return self.idea.get_discussion_id()
        elif self.idea_id:
            return Idea.get(id=self.idea_id).get_discussion_id()

    @classmethod
    def get_discussion_condition(cls, discussion_id):
        return (cls.idea_id == Idea.id) & (Idea.discussion_id == discussion_id)

    crud_permissions = CrudPermissions(
        P_ADD_IDEA, P_READ, P_EDIT_IDEA, P_EDIT_IDEA,
        P_EDIT_IDEA, P_EDIT_IDEA)

Idea.widgets = association_proxy('widget_links', 'widget')
Widget.idea_links = relationship(
    IdeaWidgetLink,
    backref=backref('widget', uselist=False))

class BaseIdeaWidgetLink(IdeaWidgetLink):
    __mapper_args__ = {
        'polymorphic_identity': 'base_idea_widget_link',
    }

BaseIdeaWidget.base_idea_link = relationship(
    BaseIdeaWidgetLink, uselist=False)

BaseIdeaWidget.base_idea = relationship(
     Idea, secondary=inspect(IdeaWidgetLink).local_table, viewonly=True,
     primaryjoin=Widget.idea_links.of_type(BaseIdeaWidgetLink),
     secondaryjoin=IdeaWidgetLink.idea,
     uselist=False)

class GeneratedIdeaWidgetLink(IdeaWidgetLink):
    __mapper_args__ = {
        'polymorphic_identity': 'generated_idea_widget_link',
    }

IdeaCreatingWidget.generated_idea_links = relationship(GeneratedIdeaWidgetLink)

IdeaCreatingWidget.generated_ideas = relationship(
     Idea, secondary=inspect(IdeaWidgetLink).local_table, viewonly=True,
     primaryjoin=Widget.idea_links.of_type(GeneratedIdeaWidgetLink),
     secondaryjoin=IdeaWidgetLink.idea)


class VoteableIdeaWidgetLink(IdeaWidgetLink):
    __mapper_args__ = {
        'polymorphic_identity': 'voteable_idea_widget_link',
    }

MultiCriterionVotingWidget.votabele_idea_links = relationship(
    VoteableIdeaWidgetLink)
