from datetime import datetime
import os.path
from random import sample as random_sample

from sqlalchemy import desc
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.orm import joinedload_all, undefer
import graphene
from graphene.pyutils.enum import Enum as PyEnum
from graphene.relay import Node
from graphene_sqlalchemy import SQLAlchemyObjectType
from graphene_sqlalchemy import SQLAlchemyConnectionField
from graphene_sqlalchemy.converter import (
    convert_column_to_string, convert_sqlalchemy_type)
from graphene_sqlalchemy.utils import get_query, is_mapped
from pyramid.httpexceptions import HTTPUnauthorized
from pyramid.security import Everyone

from assembl.auth import IF_OWNED, CrudPermissions
from assembl.auth.util import get_permissions
from assembl.lib.sqla_types import EmailString
from assembl import models
from assembl.models.action import (
    SentimentOfPost,
    LikeSentimentOfPost, DisagreeSentimentOfPost,
    DontUnderstandSentimentOfPost, MoreInfoSentimentOfPost)
from .types import SQLAlchemyInterface, SQLAlchemyUnion

convert_sqlalchemy_type.register(EmailString)(convert_column_to_string)
models.Base.query = models.Base.default_db.query_property()


class SecureObjectType(object):

    @classmethod
    def get_node(cls, id, context, info):
        try:
            result = cls.get_query(context).get(id)
        except NoResultFound:
            return None

        # The user can't retrieve a content from a different discussion
        discussion_id = context.matchdict['discussion_id']
        if result.discussion_id != discussion_id:
            raise HTTPUnauthorized()

        user_id = context.authenticated_userid or Everyone
        permissions = get_permissions(user_id, discussion_id)
        if not result.user_can(user_id, CrudPermissions.READ, permissions):
            raise HTTPUnauthorized()

        return result

# For security, always use only_fields in the Meta class to be sure we don't
# expose every fields and relations. You need at least only_fields = ('id', )
# to take effect.
# Auto exposing everything will automatically convert relations
# like AgentProfile.posts_created and create dynamically the
# object types Post, PostConnection which will conflict with those added
# manually.


def resolve_langstring(langstring, locale_code):
    """If locale_code is None, return the best lang based on user prefs,
    otherwise respect the locale_code and return the right translation or None.
    """
    if langstring is None:
        return None

    entries = langstring.entries
    if not entries:
        return None

    if locale_code is None:
        return langstring.best_entry_in_request().value

    return {e.locale_code: e.value
            for e in entries}.get(locale_code, None)


def resolve_langstring_entries(obj, attr):
    langstring = getattr(obj, attr, None)
    if langstring is None:
        return []

    entries = []
    for entry in sorted(langstring.entries, key=lambda e: e.locale_code):
        entries.append(
            LangStringEntry(
                locale_code=entry.locale_code,
                value=entry.value
            )
        )

    return entries


def langstring_from_input_entries(entries):
    """Return a LangString SA object based on GraphQL LangStringEntryInput entries.
    """
    if entries is not None and len(entries) > 0:
        langstring = models.LangString.create(
            entries[0]['value'],
            entries[0]['locale_code'])
        for entry in entries[1:]:
            locale_id = models.Locale.get_id_of(entry['locale_code'])
            langstring.add_entry(
                models.LangStringEntry(
                    langstring=langstring,
                    value=entry['value'],
                    locale_id=locale_id
                )
            )

        return langstring

    return None


def update_langstring_from_input_entries(obj, attr, entries):
    """Update langstring from getattr(obj, attr) based on GraphQL LangStringEntryInput entries.
    """
    langstring = getattr(obj, attr, None)
    if langstring is None:
        new_langstring = langstring_from_input_entries(entries)
        if new_langstring is not None:
            setattr(obj, attr, new_langstring)
        return

    current_title_entries_by_locale_code = {
        e.locale_code: e for e in langstring.entries}
    if entries is not None:
        # if we have an empty list, remove all existing entries
        if len(entries) == 0:
            for e in current_title_entries_by_locale_code.values():
                e.tombstone_date = datetime.utcnow()

        for entry in entries:
            locale_code = entry['locale_code']
            current_entry = current_title_entries_by_locale_code.get(locale_code, None)
            if current_entry is not None:
                if current_entry.value != entry['value']:
                    if not entry['value']:
                        current_entry.tombstone_date = datetime.utcnow()
                    else:
                        current_entry.change_value(entry['value'])
            else:
                locale_id = models.Locale.get_id_of(locale_code)
                langstring.add_entry(
                    models.LangStringEntry(
                        langstring=langstring,
                        value=entry['value'],
                        locale_id=locale_id
                    )
                )
    langstring.db.expire(langstring, ['entries'])
    langstring.db.flush()


class LangStringEntryFields(graphene.AbstractType):
    value = graphene.String(required=True)
    locale_code = graphene.String(required=True)


class LangStringEntry(graphene.ObjectType, LangStringEntryFields):
    pass


class LangStringEntryInput(graphene.InputObjectType, LangStringEntryFields):
    pass


sentiments_enum = PyEnum('SentimentTypes', (
    ('LIKE', 'LIKE'),
    ('DISAGREE', 'DISAGREE'),
    ('DONT_UNDERSTAND', 'DONT_UNDERSTAND'),
    ('MORE_INFO', 'MORE_INFO')))
SentimentTypes = graphene.Enum.from_enum(sentiments_enum)


class AgentProfile(SecureObjectType, SQLAlchemyObjectType):
    class Meta:
        model = models.AgentProfile
        interfaces = (Node, )
        only_fields = ('id', 'name')


# class User(AgentProfile):
#     class Meta:
#         model = models.User
#         interfaces = (Node, )
#         only_fields = ('id', 'name')  # preferredEmail


class SentimentCounts(graphene.ObjectType):
    dont_understand = graphene.Int()
    disagree = graphene.Int()
    like = graphene.Int()
    more_info = graphene.Int()


class IdeaContentLink(graphene.ObjectType):
    idea_id = graphene.ID(required=True)
    type = graphene.String(required=True)


class PostInterface(SQLAlchemyInterface):
    class Meta:
        model = models.Post
        only_fields = ('creation_date', 'creator')
        # Don't add id in only_fields in an interface or the the id of Post
        # will be just the primary key, not the base64 type:id

    subject = graphene.String(lang=graphene.String())
    body = graphene.String(lang=graphene.String())
    sentiment_counts = graphene.Field(SentimentCounts)
    my_sentiment = graphene.Field(type=SentimentTypes)
    indirect_idea_content_links = graphene.List(IdeaContentLink)
    parent_id = graphene.ID()

    def resolve_subject(self, args, context, info):
        subject = resolve_langstring(self.get_subject(), args.get('lang'))
        return subject

    def resolve_body(self, args, context, info):
        body = resolve_langstring(self.get_body(), args.get('lang'))
        return body

    def resolve_sentiment_counts(self, args, context, info):
        sentiment_counts = self.sentiment_counts
        return SentimentCounts(
            dont_understand=sentiment_counts['dont_understand'],
            disagree=sentiment_counts['disagree'],
            like=sentiment_counts['like'],
            more_info=sentiment_counts['more_info'],
        )

    def resolve_my_sentiment(self, args, context, info):
        my_sentiment = self.my_sentiment
        if my_sentiment is None:
            return None

        return my_sentiment.name.upper()

    def resolve_indirect_idea_content_links(self, args, context, info):
        links = [(models.Idea.get_database_id(link['idIdea']), link['@type'])
                    for link in self.indirect_idea_content_links_with_cache()]
        return [IdeaContentLink(idea_id=Node.to_global_id('Idea', idea_id),
                                type=type)
                for idea_id, type in links]

    def resolve_parent_id(self, args, context, info):
        if self.parent_id is None:
            return None

        return Node.to_global_id('Post', self.parent_id)


class Post(SecureObjectType, SQLAlchemyObjectType):
    class Meta:
        model = models.Post
        interfaces = (Node, PostInterface)
        only_fields = ('id', )  # inherits fields from Post interface only

    @classmethod
    def is_type_of(cls, root, context, info):
        if isinstance(root, cls):
            return True
        if not is_mapped(type(root)):
            raise Exception((
                'Received incompatible instance "{}".'
            ).format(root))
        return (isinstance(root, cls._meta.model)
                and type(root) != type(models.PropositionPost))


class PropositionPost(Post):
    class Meta:
        model = models.PropositionPost
        interfaces = (Node, PostInterface)
        only_fields = ('id', )  # inherits fields from Post interface only


class PostUnion(SQLAlchemyUnion):
    class Meta:
        types = (PropositionPost, Post)
        model = models.Post

    @classmethod
    def resolve_type(cls, instance, context, info):
        if isinstance(instance, graphene.ObjectType):
            return type(instance)
        elif isinstance(instance, models.PropositionPost): # must be above Post
            return PropositionPost
        elif isinstance(instance, models.Post):
            return Post


class PostConnection(graphene.Connection):
    class Meta:
        node = PostUnion


class Video(graphene.ObjectType):
    title = graphene.String()
    description = graphene.String()
    html_code = graphene.String()
    title_entries = graphene.List(LangStringEntry)
    description_entries = graphene.List(LangStringEntry)


class Idea(SecureObjectType, SQLAlchemyObjectType):
    class Meta:
        model = models.Idea
        interfaces = (Node, )
        only_fields = ('id', 'short_title', )

    title = graphene.String(lang=graphene.String())
    title_entries = graphene.List(LangStringEntry)
    description = graphene.String(lang=graphene.String())
    description_entries = graphene.List(LangStringEntry)
    children = graphene.List(lambda: Idea)
    img_url = graphene.String()
    order = graphene.Float()
    num_posts = graphene.Int()
    num_contributors = graphene.Int()
    parent_id = graphene.ID()
    posts = SQLAlchemyConnectionField(PostConnection)
    contributors = graphene.List(AgentProfile)

    @classmethod
    def is_type_of(cls, root, context, info):
        # This is the method defined in SQLAlchemyObjectType where
        # we changed the isinstance by a type comparison.
        # For a node query, graphql in
        # graphene/types/typemap.py(43)resolve_type()
        # which calls graphql/execution/executor.py(351)get_default_resolve_type_fn()
        # will try to know the object type from the SA object.
        # It actually iterate over all registered object types and return
        # the first one where is_type_of return True.
        # And here we have in the following order Idea, Question, Thematic.
        # So a node query on a Thematic or Question was returning the Idea object type.
        # Here we fix the issue by overriding the is_type_of method
        # for the Idea type to do a type comparison so that
        # models.Question/models.Thematic which
        # inherits from models.Idea doesn't return true
        if isinstance(root, cls):
            return True
        if not is_mapped(type(root)):
            raise Exception((
                'Received incompatible instance "{}".'
            ).format(root))
        # return isinstance(root, cls._meta.model)  # this was the original code
        return type(root) == cls._meta.model or type(root) == models.RootIdea

    def resolve_title(self, args, context, info):
        title = resolve_langstring(self.title, args.get('lang'))
        # If the idea was created from the old api or v1 interface, we don't
        # have title, return short_title.
        if title is None:
            return self.short_title

        return title

    def resolve_title_entries(self, args, context, info):
        return resolve_langstring_entries(self, 'title')

    def resolve_description(self, args, context, info):
        return resolve_langstring(self.description, args.get('lang'))

    def resolve_description_entries(self, args, context, info):
        return resolve_langstring_entries(self, 'description')

    def resolve_children(self, args, context, info):
        return self.get_children()

    def resolve_img_url(self, args, context, info):
        if self.attachments:
            return self.attachments[0].external_url

    def resolve_order(self, args, context, info):
        return self.get_order_from_first_parent()

    def resolve_parent_id(self, args, context, info):
        parents = self.get_parents()
        if not parents:
            return None

        return Node.to_global_id('Idea', parents[0].id)

    def resolve_posts(self, args, context, info):
        discussion_id = context.matchdict['discussion_id']
        discussion = models.Discussion.get(discussion_id)
        related = self.get_related_posts_query(True)
        # The related query returns a list of (<PropositionPost id=2 >, None) instead of <PropositionPost id=2 > when authenticated, this is why we do another query here:
        Post = models.Post
        query = Post.query.join(
            related, Post.id == related.c.post_id
            ).filter(Post.publication_state == models.PublicationStates.PUBLISHED
            ).order_by(desc(Post.creation_date), Post.id
            ).options(
                joinedload_all(Post.creator),
                undefer(Post.idea_content_links_above_post)
            )
        if len(discussion.discussion_locales) > 1:
            query = query.options(*models.Content.subqueryload_options())
        else:
            query = query.options(*models.Content.joinedload_options())

        # pagination is done after that, no need to do it ourself
        return query

    def resolve_contributors(self, args, context, info):
        contributor_ids = [cid for (cid,) in self.get_contributors_query()]
        contributors = [models.AgentProfile.get(cid) for cid in contributor_ids]
        return contributors


class Question(SecureObjectType, SQLAlchemyObjectType):
    class Meta:
        model = models.Question
        interfaces = (Node, )
        only_fields = ('id', )

    title = graphene.String(lang=graphene.String())
    title_entries = graphene.List(LangStringEntry)
    posts = SQLAlchemyConnectionField(PostConnection, random=graphene.Boolean())

    def resolve_title(self, args, context, info):
        title = resolve_langstring(self.title, args.get('lang'))
        return title

    def resolve_title_entries(self, args, context, info):
        return resolve_langstring_entries(self, 'title')

    def resolve_posts(self, args, context, info):
        discussion_id = context.matchdict['discussion_id']
        discussion = models.Discussion.get(discussion_id)
        random = args.get('random', False)
        Post = models.Post
        related = self.get_related_posts_query(True)
        # If random is True returns 10 posts, the first one is the latest post created by the user,
        # then the remaining ones are in random order.
        # If random is False, return all the posts in creation_date desc order.
        if random:
            user_id = context.authenticated_userid
            if user_id is None:
                first_post = None
            else:
                first_post = Post.query.join(
                    related, Post.id == related.c.post_id
                    ).filter(Post.creator_id == user_id
                    ).order_by(desc(Post.creation_date), Post.id).first()

            query = Post.default_db.query(Post.id).join(
                related, Post.id == related.c.post_id
                ).filter(Post.publication_state == models.PublicationStates.PUBLISHED)
            # retrieve ids, do the random and get the posts for these ids
            post_ids = [e[0] for e in query]
            limit = args.get('first', 10)
            if first_post is not None:
                first_post_id = first_post.id
                post_ids = [post_id for post_id in post_ids if post_id != first_post_id]
                limit -= 1

            random_posts_ids = random_sample(
                post_ids, min(len(post_ids), limit))
            query = Post.query.filter(Post.id.in_(random_posts_ids)
                ).options(
                    joinedload_all(Post.creator),
                )
            if len(discussion.discussion_locales) > 1:
                query = query.options(
                    models.LangString.subqueryload_option(Post.body))
            else:
                query = query.options(
                    models.LangString.joinedload_option(Post.body))

            if first_post is not None:
                query = [first_post] + query.all()

        else:
            # The related query returns a list of (<PropositionPost id=2 >, None) instead of <PropositionPost id=2 > when authenticated, this is why we do another query here:
            query = Post.query.join(
                related, Post.id == related.c.post_id
                ).filter(Post.publication_state == models.PublicationStates.PUBLISHED
                ).order_by(desc(Post.creation_date), Post.id
                ).options(
                    joinedload_all(Post.creator),
                )
            if len(discussion.discussion_locales) > 1:
                query = query.options(
                    models.LangString.subqueryload_option(Post.body))
            else:
                query = query.options(
                    models.LangString.joinedload_option(Post.body))

        # pagination is done after that, no need to do it ourself
        return query


class Thematic(SecureObjectType, SQLAlchemyObjectType):
    class Meta:
        model = models.Thematic
        interfaces = (Node, )
        only_fields = ('id', 'identifier')

    title = graphene.String(lang=graphene.String())
    title_entries = graphene.List(LangStringEntry)
    description = graphene.String(lang=graphene.String())
    description_entries = graphene.List(LangStringEntry)
    questions = graphene.List(Question)
    video = graphene.Field(Video, lang=graphene.String())
    img_url = graphene.String()
    num_posts = graphene.Int()
    num_contributors = graphene.Int()
    order = graphene.Float()

    def resolve_title(self, args, context, info):
        title = resolve_langstring(self.title, args.get('lang'))
        return title

    def resolve_title_entries(self, args, context, info):
        return resolve_langstring_entries(self, 'title')

    def resolve_description(self, args, context, info):
        return resolve_langstring(self.description, args.get('lang'))

    def resolve_description_entries(self, args, context, info):
        return resolve_langstring_entries(self, 'description')

    def resolve_questions(self, args, context, info):
        return self.get_children()

    def resolve_video(self, args, context, info):
        title = resolve_langstring(self.video_title, args.get('lang'))
        title_entries = resolve_langstring_entries(self, 'video_title')
        description = resolve_langstring(self.video_description, args.get('lang'))
        description_entries = resolve_langstring_entries(self, 'video_description')
        if not (title_entries or description_entries or self.video_html_code):
            return None

        return Video(
            title=title,
            title_entries=title_entries,
            description=description,
            description_entries=description_entries,
            html_code=self.video_html_code,
        )

    def resolve_img_url(self, args, context, info):
        if self.attachments:
            return self.attachments[0].external_url

    def resolve_order(self, args, context, info):
        return self.get_order_from_first_parent()


class Query(graphene.ObjectType):
    node = Node.Field()
    posts = SQLAlchemyConnectionField(PostConnection, idea_id=graphene.ID())
    root_idea = graphene.Field(Idea)
    ideas = graphene.List(Idea)
    thematics = graphene.List(Thematic, identifier=graphene.String(required=True))

    def resolve_root_idea(self, args, context, info):
        discussion_id = context.matchdict['discussion_id']
        discussion = models.Discussion.get(discussion_id)
        return discussion.root_idea

    def resolve_ideas(self, args, context, info):
        model = models.Idea
        query = get_query(model, context)
        discussion_id = context.matchdict['discussion_id']
        discussion = models.Discussion.get(discussion_id)
        root_idea_id = discussion.root_idea.id
        descendants_query = model.get_descendants_query(
            root_idea_id, inclusive=True)
        query = query.filter(model.id.in_(descendants_query)
            ).filter(model.hidden == False).order_by(model.id)
        return query

    def resolve_posts(self, args, context, info):
        discussion_id = context.matchdict['discussion_id']
        discussion = models.Discussion.get(discussion_id)
        idea_id = args.get('idea_id', None)
        if idea_id is not None:
            id_ = int(Node.from_global_id(idea_id)[1])
            idea = models.Idea.get(id_)
            if idea.discussion_id != discussion_id:
                return None
        else:
            discussion = models.Discussion.get(discussion_id)
            idea = discussion.root_idea

        Post = models.Post
        related = idea.get_related_posts_query(True)
        query = Post.query.join(
            related, Post.id == related.c.post_id
            ).filter(Post.publication_state == models.PublicationStates.PUBLISHED
            ).order_by(desc(Post.creation_date), Post.id
            ).options(
                joinedload_all(Post.creator),
                undefer(Post.idea_content_links_above_post)
            )
        if len(discussion.discussion_locales) > 1:
            query = query.options(*models.Content.subqueryload_options())
        else:
            query = query.options(*models.Content.joinedload_options())

        # pagination is done after that, no need to do it ourself
        return query

    def resolve_thematics(self, args, context, info):
        identifier = args.get('identifier', None)
        discussion_id = context.matchdict['discussion_id']
        discussion = models.Discussion.get(discussion_id)
        root_thematic = get_root_thematic_for_phase(discussion, identifier)
        if root_thematic is None:
            return []

        return root_thematic.get_children()


class VideoInput(graphene.InputObjectType):
    title_entries = graphene.List(LangStringEntryInput)
    description_entries = graphene.List(LangStringEntryInput)
    html_code = graphene.String()


class QuestionInput(graphene.InputObjectType):
    id = graphene.ID()
    title_entries = graphene.List(LangStringEntryInput, required=True)


def get_root_thematic_for_phase(discussion, identifier):
    """Return root thematic for the given phase `identifier` on `discussion`.
    """
    root_thematic = [idea
                     for idea in discussion.root_idea.get_children()
                     if getattr(idea, 'identifier', '') == identifier]
    return root_thematic[0] if root_thematic else None


def create_root_thematic(discussion, identifier):
    """Create the root thematic (hidden) for the given phase `identifier`
    on `discussion`.
    """
    short_title = u'Phase {}'.format(identifier)
    root_thematic = models.Thematic(
        discussion_id=discussion.id,
        short_title=short_title,
        title=langstring_from_input_entries(
            [{'locale_code': 'en', 'value': short_title}]),
        identifier=identifier,
        hidden=True)
    discussion.root_idea.children.append(root_thematic)
    return root_thematic


# How the file upload works
# With the https://github.com/jaydenseric/apollo-upload-client
# networkInterface, if there is a File object in a graphql variable, the File data
# is appended to the POST body as a part with an identifier starting with 'variables.',
# For example if we use 'img' File variable in a mutation,
# 'variables.img' will be available in context.POST, 'img' is removed from the
# variables in the json by apollo-upload-client, but graphql-wsgi put back
# {'img': 'variables.img'}
# in the variables, so here `image` input argument will be 'variables.img'
# (assuming assigning image: $img in the mutation)
class CreateThematic(graphene.Mutation):
    class Input:
        # Careful, having required=True on a graphene.List only means
        # it can't be None, having an empty [] is perfectly valid.
        title_entries = graphene.List(LangStringEntryInput, required=True)
        description_entries = graphene.List(LangStringEntryInput)
        identifier = graphene.String(required=True)
        video = graphene.Argument(VideoInput)
        questions = graphene.List(QuestionInput)
        image = graphene.String()  # this is the identifier of the part in a multipart POST
        order = graphene.Float()

    thematic = graphene.Field(lambda: Thematic)

    @staticmethod
    def mutate(root, args, context, info):
        cls = models.Thematic
        discussion_id = context.matchdict['discussion_id']
        discussion = models.Discussion.get(discussion_id)
        user_id = context.authenticated_userid or Everyone

        permissions = get_permissions(user_id, discussion_id)
        allowed = cls.user_can_cls(user_id, CrudPermissions.CREATE, permissions)
        if not allowed or (allowed == IF_OWNED and user_id == Everyone):
            raise HTTPUnauthorized()

        identifier = args.get('identifier')
        with cls.default_db.no_autoflush:
            title_entries = args.get('title_entries')
            if len(title_entries) == 0:
                raise Exception('Thematic titleEntries needs at least one entry')
                # Better to have this message than
                # 'NoneType' object has no attribute 'owner_object'
                # when creating the saobj below if title=None

            title_langstring = langstring_from_input_entries(title_entries)
            description_langstring = langstring_from_input_entries(args.get('description_entries'))
            kwargs = {}
            if description_langstring is not None:
                kwargs['description'] = description_langstring

            video = args.get('video')
            if video is not None:
                video_title = langstring_from_input_entries(video.get('title_entries', None))
                if video_title is not None:
                    kwargs['video_title'] = video_title

                video_description = langstring_from_input_entries(
                    video.get('description_entries', None))
                if video_description is not None:
                    kwargs['video_description'] = video_description

                video_html_code = video.get('html_code', None)
                if video_html_code is not None:
                    kwargs['video_html_code'] = video_html_code

            # Our thematic, because it inherits from Idea, needs to be
            # associated to the root idea of the discussion.
            # We create a hidden root thematic, corresponding to the
            # `identifier` phase, child of the root idea,
            # and add our thematic as a child of this root thematic.
            root_thematic = get_root_thematic_for_phase(discussion, identifier)
            if root_thematic is None:
                root_thematic = create_root_thematic(discussion, identifier)

            # take the first entry and set it for short_title
            short_title = title_entries[0]['value']
            saobj = cls(
                discussion_id=discussion_id,
                title=title_langstring,
                short_title=short_title,
                identifier=identifier,
                **kwargs)
            db = saobj.db
            db.add(saobj)
            order = len(root_thematic.get_children()) + 1.0
            db.add(
                models.IdeaLink(source=root_thematic, target=saobj,
                         order=args.get('order', order)))

            # add uploaded image as an attachment to the idea
            image = args.get('image')
            if image is not None:
                filename = os.path.basename(context.POST[image].filename)
                mime_type = context.POST[image].type
                uploaded_file = context.POST[image].file
                uploaded_file.seek(0)
                data = uploaded_file.read()
                document = models.File(
                    discussion=discussion,
                    mime_type=mime_type,
                    title=filename,
                    data=data)
                attachment = models.IdeaAttachment(
                    document=document,
                    idea=saobj,
                    discussion=discussion,
                    creator_id=context.authenticated_userid,
                    title=filename,
                    attachmentPurpose="EMBED_ATTACHMENT"
                )

            db.flush()

            questions_input = args.get('questions')
            if questions_input is not None:
                for idx, question_input in enumerate(questions_input):
                    title_ls = langstring_from_input_entries(
                        question_input['title_entries'])
                    question = models.Question(
                        title=title_ls,
                        discussion_id=discussion_id
                    )
                    db.add(
                        models.IdeaLink(source=saobj, target=question,
                                        order=idx + 1.0))
                db.flush()

        return CreateThematic(thematic=saobj)


class UpdateThematic(graphene.Mutation):
    class Input:
        id = graphene.ID(required=True)
        title_entries = graphene.List(LangStringEntryInput)
        description_entries = graphene.List(LangStringEntryInput)
        identifier = graphene.String()
        video = graphene.Argument(VideoInput)
        questions = graphene.List(QuestionInput)
        image = graphene.String()  # this is the identifier of the part in a multipart POST
        order = graphene.Float()

    thematic = graphene.Field(lambda: Thematic)

    @staticmethod
    def mutate(root, args, context, info):
        cls = models.Thematic
        discussion_id = context.matchdict['discussion_id']
        discussion = models.Discussion.get(discussion_id)
        user_id = context.authenticated_userid or Everyone

        thematic_id = args.get('id')
        id_ = int(Node.from_global_id(thematic_id)[1])
        thematic = cls.get(id_)

        permissions = get_permissions(user_id, discussion_id)
        allowed = thematic.user_can(user_id, CrudPermissions.UPDATE, permissions)
        if not allowed or (allowed == IF_OWNED and user_id == Everyone):
            raise HTTPUnauthorized()

        with cls.default_db.no_autoflush:
            title_entries = args.get('title_entries')
            if title_entries is not None and len(title_entries) == 0:
                raise Exception('Thematic titleEntries needs at least one entry')
                # Better to have this message than
                # 'NoneType' object has no attribute 'owner_object'
                # when creating the saobj below if title=None

            update_langstring_from_input_entries(thematic, 'title', title_entries)
            update_langstring_from_input_entries(thematic, 'description', args.get('description_entries'))
            kwargs = {}
            video = args.get('video', None)
            if video is not None:
                update_langstring_from_input_entries(
                    thematic, 'video_title', video.get('title_entries', []))
                update_langstring_from_input_entries(
                    thematic, 'video_description',
                    video.get('description_entries', []))
                kwargs['video_html_code'] = video.get('html_code', None)

            # take the first entry and set it for short_title
            if title_entries is not None:
                kwargs['short_title'] = title_entries[0]['value']

            if args.get('identifier') is not None:
                kwargs['identifier'] = args.get('identifier')

            for attr, value in kwargs.items():
                setattr(thematic, attr, value)

            db = thematic.db

            # change order if needed
            order = args.get('order')
            if order:
                thematic.source_links[0].order = order

            # add uploaded image as an attachment to the idea
            image = args.get('image')
            if image is not None:
                filename = os.path.basename(context.POST[image].filename)
                mime_type = context.POST[image].type
                uploaded_file = context.POST[image].file
                uploaded_file.seek(0)
                data = uploaded_file.read()
                document = models.File(
                    discussion=discussion,
                    mime_type=mime_type,
                    title=filename,
                    data=data)
                # if there is already an attachment, remove it with the
                # associated document (image)
                if thematic.attachments:
                    db.delete(thematic.attachments[0].document)
                    thematic.attachments.remove(thematic.attachments[0])

                attachment = models.IdeaAttachment(
                    document=document,
#                    idea=thematic,
                    discussion=discussion,
                    creator_id=context.authenticated_userid,
                    title=filename,
                    attachmentPurpose="EMBED_ATTACHMENT"
                )
                thematic.attachments.append(attachment)
            db.flush()

            questions_input = args.get('questions')
            existing_questions = {question.id: question for question in thematic.get_children()}
            updated_questions = set()
            if questions_input is not None:
                for idx, question_input in enumerate(questions_input):
                    if question_input.get('id', None) is not None:
                        id_ = int(Node.from_global_id(question_input['id'])[1])
                        updated_questions.add(id_)
                        question = models.Question.get(id_)
                        update_langstring_from_input_entries(
                            question, 'title', question_input['title_entries'])
                        # modify question order
                        question.source_links[0].order = idx + 1.0
                    else:
                        title_ls = langstring_from_input_entries(
                            question_input['title_entries'])
                        question = models.Question(
                            title=title_ls,
                            discussion_id=discussion_id
                        )
                        db.add(
                            models.IdeaLink(source=thematic, target=question,
                                     order=idx + 1.0))

                # remove question (tombstone it) that are not in questions_input
                for question_id in set(existing_questions.keys()
                        ).difference(updated_questions):
                    existing_questions[question_id].tombstone_date = datetime.utcnow()

            db.flush()

        return UpdateThematic(thematic=thematic)


class DeleteThematic(graphene.Mutation):
    class Input:
        thematic_id = graphene.ID(required=True)

    success = graphene.Boolean()

    @staticmethod
    def mutate(root, args, context, info):
        discussion_id = context.matchdict['discussion_id']
        user_id = context.authenticated_userid or Everyone

        thematic_id = args.get('thematic_id')
        thematic_id = int(Node.from_global_id(thematic_id)[1])
        thematic = models.Thematic.get(thematic_id)

        permissions = get_permissions(user_id, discussion_id)
        allowed = models.Thematic.user_can_cls(user_id, CrudPermissions.DELETE, permissions)
        if not allowed or (allowed == IF_OWNED and user_id == Everyone):
            raise HTTPUnauthorized()

        thematic.tombstone_date = datetime.utcnow()
        thematic.db.flush()
        return DeleteThematic(success=True)


class CreatePost(graphene.Mutation):
    class Input:
        subject = graphene.String()
        body = graphene.String(required=True)
        idea_id = graphene.ID(required=True)
        # TODO: for a real post (not a proposal), we need to handle parent_id
        # see related code in views/api/post.py

    post = graphene.Field(lambda: PostUnion)

    @staticmethod
    def mutate(root, args, context, info):
        discussion_id = context.matchdict['discussion_id']

        user_id = context.authenticated_userid or Everyone

        idea_id = args.get('idea_id')
        idea_id = int(Node.from_global_id(idea_id)[1])
        in_reply_to_idea = models.Idea.get(idea_id)
        if isinstance(in_reply_to_idea, models.Question):
            cls = models.PropositionPost
        else:
            cls = models.Post

        permissions = get_permissions(user_id, discussion_id)
        allowed = cls.user_can_cls(user_id, CrudPermissions.CREATE, permissions)
        if not allowed or (allowed == IF_OWNED and user_id == Everyone):
            raise HTTPUnauthorized()

        with cls.default_db.no_autoflush:
            subject = args.get('subject')
            body = args.get('body')
            if subject is None:
                # TODO for real post, need the same logic than in views/api/post.py
                subject_entries = [
                    {'value': u'Proposition', u'locale_code': u'und'}
                ]
            else:
                subject_entries = [
                    {'value': subject, u'locale_code': u'und'}
                ]

            body_entries = [
                {'value': body, u'locale_code': u'und'}
            ]

            subject_langstring = langstring_from_input_entries(subject_entries)
            body_langstring = langstring_from_input_entries(body_entries)
            discussion = models.Discussion.get(discussion_id)
            new_post = cls(
                discussion=discussion,
                subject=subject_langstring,
                body=body_langstring,
                creator_id=user_id
            )
            db = new_post.db
            db.add(new_post)
            idea_post_link = models.IdeaRelatedPostLink(
                creator_id=user_id,
                content=new_post,
                idea=in_reply_to_idea
            )
            db.add(idea_post_link)
            db.flush()

        return CreatePost(post=new_post)


class AddSentiment(graphene.Mutation):
    class Input:
        post_id = graphene.ID(required=True)
        type = graphene.Argument(
            type=SentimentTypes,
            required=True
        )

    post = graphene.Field(lambda: PostUnion)

    @staticmethod
    def mutate(root, args, context, info):
        discussion_id = context.matchdict['discussion_id']
        discussion = models.Discussion.get(discussion_id)

        user_id = context.authenticated_userid or Everyone

        post_id = args.get('post_id')
        post_id = int(Node.from_global_id(post_id)[1])
        post = models.Post.get(post_id)

        permissions = get_permissions(user_id, discussion_id)
        allowed = SentimentOfPost.user_can_cls(user_id, CrudPermissions.CREATE, permissions)
        if not allowed or (allowed == IF_OWNED and user_id == Everyone):
            raise HTTPUnauthorized()

        sentiment_type = args.get('type')
        if SentimentTypes.LIKE.name == sentiment_type:
            sentiment = LikeSentimentOfPost(
                post=post, discussion=discussion, actor_id=user_id)
        elif SentimentTypes.DISAGREE.name == sentiment_type:
            sentiment = DisagreeSentimentOfPost(
                post=post, discussion=discussion, actor_id=user_id)
        elif SentimentTypes.DONT_UNDERSTAND.name == sentiment_type:
            sentiment = DontUnderstandSentimentOfPost(
                post=post, discussion=discussion, actor_id=user_id)
        elif SentimentTypes.MORE_INFO.name == sentiment_type:
            sentiment = MoreInfoSentimentOfPost(
                post=post, discussion=discussion, actor_id=user_id)

        sentiment = sentiment.handle_duplication(
            permissions=permissions, user_id=user_id)
        sentiment.db.add(sentiment)
        sentiment.db.flush()
        return AddSentiment(post=post)


class DeleteSentiment(graphene.Mutation):
    class Input:
        post_id = graphene.ID(required=True)

    post = graphene.Field(lambda: PostUnion)

    @staticmethod
    def mutate(root, args, context, info):
        discussion_id = context.matchdict['discussion_id']
        user_id = context.authenticated_userid or Everyone

        post_id = args.get('post_id')
        post_id = int(Node.from_global_id(post_id)[1])
        post = models.Post.get(post_id)

        permissions = get_permissions(user_id, discussion_id)
        allowed = SentimentOfPost.user_can_cls(user_id, CrudPermissions.DELETE, permissions)
        if not allowed or (allowed == IF_OWNED and user_id == Everyone):
            raise HTTPUnauthorized()

        post.my_sentiment.tombstone_date = datetime.utcnow()
        post.db.flush()
        return DeleteSentiment(post=post)


class Mutations(graphene.ObjectType):
    create_thematic = CreateThematic.Field()
    update_thematic = UpdateThematic.Field()
    delete_thematic = DeleteThematic.Field()
    create_post = CreatePost.Field()
    add_sentiment = AddSentiment.Field()
    delete_sentiment = DeleteSentiment.Field()


Schema = graphene.Schema(query=Query, mutation=Mutations)


def print_schema_json(schema):
    import json
    schema_dict = schema.introspect()
    with open('/tmp/schema.json', 'w') as outfile:
        json.dump(schema_dict, outfile)


'''
$ pshell local.ini
import json
from assembl.graphql.schema import Schema as schema
from webtest import TestRequest
request = TestRequest.blank('/', method="POST")
request.matchdict = {"discussion_id": 6}
# take the first sysadmin:
userid = models.User.default_db.query(models.User).join(models.User.roles).filter(models.Role.id == 7)[0:1][0].id
request.authenticated_userid = userid

# and after that, execute a query or mutation....
# For mutations, see examples in tests/test_graphql.py (replace graphql_request by request)
# In pshell, you need to db.commit() if you want a mutation to be persistent.

#print the schema as text:
print str(schema)

#schema.execute returns a ExecutionResult object with data and errors attributes on it.

#get node:
print json.dumps(schema.execute('query { node(id:"UG9zdDoyMzU5") { ... on Post { id, creator { name } } } }', context_value=request).data, indent=2)

# get posts for a specific idea:
print json.dumps(schema.execute('query { node(id:"SWRlYToyNDU0") { ... on Idea { id, posts { edges { node { ... on PostInterface { subject, body, creationDate, creator { name } } } } } } } }', context_value=request).data, indent=2)

#get ideas:
print json.dumps(schema.execute('query { ideas(first: 5) { pageInfo { endCursor hasNextPage } edges { node { id } } } }', context_value=request).data, indent=2)

#get posts:
print json.dumps(schema.execute('query { posts(first: 5) { pageInfo { endCursor hasNextPage } edges { node { ... on Post {id, creator { name }, subject, body, sentimentCounts {dontUnderstand disagree like moreInfo }} } } } }', context_value=request).data, indent=2)
# curl --silent -XPOST -H "Content-Type:application/json" -d '{ "query": "query { posts(first: 5) { pageInfo { endCursor hasNextPage } edges { node { ... on Post {id, creator { name }} } } } }" }' http://localhost:6543/sandbox/graphql
# to be authenticated add the assembl_session cookie (look the value in the Chrome console):
# -H 'Cookie:assembl_session=d8deabe718595c01d3899aa686ac027193cc7d6984bd73b14afc42738d798018629b6e8a;'

#get thematics with questions:
print json.dumps(schema.execute('query { thematics(identifier:"survey") { id, title, description, numPosts, numContributors, questions { title }, video {title, description, htmlCode} } }', context_value=request).data, indent=2)

'''
