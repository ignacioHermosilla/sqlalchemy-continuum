"""
Activity
--------
The ActivityPlugin is the most powerful plugin for tracking changes of
individual entities. If you use ActivityPlugin you probably don't need to use
TransactionChanges nor TransactionMeta plugins.

You can initalize the ActivityPlugin by adding it to versioning manager.

::

    activity_plugin = ActivityPlugin()

    make_versioned(plugins=[activity_plugin])


ActivityPlugin uses single database table for tracking activities. This table
follows the data structure in `activity stream specification`_, but it comes
with a nice twist:

    ==============  =========== =============
    Column          Type        Description
    ==============  =========== =============
    id              BigInteger  The primary key of the activity
    verb            Unicode     Verb defines the action of the activity
    data            JSON        Additional data for the activity in JSON format
    transaction_id  BigInteger  The transaction this activity was associated
                                with
    object_id       BigInteger  The primary key of the object. Object can be
                                any entity which has an integer as primary key.
    object_type     Unicode     The type of the object (class name as string)

    object_tx_id    BigInteger  The last transaction_id associated with the
                                object. This is used for efficiently fetching
                                the object version associated with this
                                activity.

    target_id       BigInteger  The primary key of the target. Target can be
                                any entity which has an integer as primary key.
    target_type     Unicode     The of the target (class name as string)

    target_tx_id    BigInteger  The last transaction_id associated with the
                                target.
    ==============  =========== =============


Each Activity has relationships to actor, object and target but it also holds
information about the associated transaction and about the last associated
transactions with the target and object. This allows each activity to also have
object_version and target_version relationships for introspecting what those
objects and targets were in given point in time. All these relationship
properties use `generic relationships`_ of the SQLAlchemy-Utils package.



Once your models have been configured you can get the Activity model from the
ActivityPlugin class with activity_cls property::


    Activity = activity_plugin.activity_cls


Now let's say we have model called Article and Category. Each Article has one
Category. Activities should be created along with the changes you make on
these models::

    article = Article(name=u'Some article')
    session.add(article)
    first_activity = Activity(verb=u'create', object=article)
    session.add(first_activity)
    session.commit()


The object property of the Activity object holds the current object and the
object_version holds the object version at the time when the activity was
created.


    article.name = u'Some article updated!'
    second_activity = Activity(verb=u'update', object=article)
    session.add(second_activity)
    session.commit()

    second_activity.object.name  # u'Some article updated!'
    first_activity.object.name  # u'Some article updated!'

    first_activity.object_version.name  # u'Some article'


.. _activity stream specification:
    http://www.activitystrea.ms
.. _generic relationships:
    http://sqlalchemy-utils.readthedocs.org/en/latest/generic_relationship.html
"""

import sqlalchemy as sa
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy_utils import JSONType, generates, generic_relationship

from .base import Plugin
from ..factory import ModelFactory
from ..utils import version_class


class ActivityBase(object):
    id = sa.Column(sa.BigInteger, primary_key=True, autoincrement=True)

    verb = sa.Column(sa.Unicode(255))

    @hybrid_property
    def actor(self):
        self.transaction.user


class ActivityFactory(ModelFactory):
    model_name = 'Activity'

    def create_class(self):
        """
        Create Activity class.
        """
        class Activity(
            self.manager.declarative_base,
            ActivityBase
        ):
            __tablename__ = 'activity'
            manager = self

            transaction_id = sa.Column(
                sa.BigInteger,
                index=True,
                nullable=False
            )

            data = sa.Column(JSONType)

            object_type = sa.Column(sa.String(255))

            object_id = sa.Column(sa.BigInteger)

            object_tx_id = sa.Column(sa.BigInteger)

            target_type = sa.Column(sa.String(255))

            target_id = sa.Column(sa.BigInteger)

            target_tx_id = sa.Column(sa.BigInteger)

            @generates(object_tx_id)
            def generate_object_transaction_id(self):
                session = sa.orm.object_session(self)
                if self.object:
                    version_cls = version_class(self.object.__class__)
                    return session.query(
                        sa.func.max(version_cls.transaction_id)
                    ).scalar()

            @generates(target_tx_id)
            def generate_target_transaction_id(self):
                session = sa.orm.object_session(self)
                if self.target:
                    version_cls = version_class(self.target.__class__)
                    return session.query(
                        sa.func.max(version_cls.transaction_id)
                    ).scalar()

            object = generic_relationship(
                object_type, object_id
            )

            @hybrid_property
            def object_version_type(self):
                return self.object_type + 'Version'

            @object_version_type.expression
            def object_version_type(cls):
                return sa.func.concat(cls.object_type, 'Version')

            object_version = generic_relationship(
                object_version_type, (object_id, object_tx_id)
            )

            target = generic_relationship(
                target_type, target_id
            )

            @hybrid_property
            def target_version_type(self):
                return self.target_type + 'Version'

            @target_version_type.expression
            def target_version_type(cls):
                return sa.func.concat(cls.target_type, 'Version')

            target_version = generic_relationship(
                target_version_type, (target_id, target_tx_id)
            )

        Activity.transaction = sa.orm.relationship(
            self.manager.transaction_cls,
            backref=sa.orm.backref(
                'activities',
            ),
            primaryjoin=(
                '%s.id == Activity.transaction_id' %
                self.manager.transaction_cls.__name__
            ),
            foreign_keys=[Activity.transaction_id]
        )
        return Activity


class ActivityPlugin(Plugin):
    def after_build_models(self, manager):
        self.activity_cls = ActivityFactory(manager)()
        manager.activity_cls = self.activity_cls

    def is_session_modified(self, session):
        """
        Return that the session has been modified if the session contains an
        activity class.

        :param session: SQLAlchemy session object
        """
        return any(isinstance(obj, self.activity_cls) for obj in session)

    def before_flush(self, uow, session):
        for obj in session:
            if isinstance(obj, self.activity_cls):
                obj.transaction = uow.current_transaction

    def after_version_class_built(self, parent_cls, version_cls):
        pass
