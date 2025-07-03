from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import timedelta, datetime, timezone
import secrets

class Users(UserMixin, db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True,
                                                unique=True, nullable=False)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True, unique=True, nullable=False)
    password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))

    token: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), index=True, unique=True)
    token_expiration: so.Mapped[Optional[datetime]]

    def __repr__(self):
        return '<Users {}>'.format(self.username)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def from_dict(self, data, new_user=False):
        for field in ['username', 'email']:
            if field in data:
                setattr(self, field, data[field])
        if new_user and 'password' in data:
            self.set_password(data['password'])

    def get_token(self, expires_in=3600):
        now = datetime.now(timezone.utc)
        if self.token and self.token_expiration.astimezone(timezone.utc) > now + timedelta(seconds=60):
            return self.token
        self.token = secrets.token_hex(16)
        self.token_expiration = now + timedelta(seconds=expires_in)
        db.session.add(self)
        return self.token

    def revoke_token(self):
        self.token_expiration = datetime.now(timezone.utc) - timedelta(
            seconds=1)

    @staticmethod
    def check_token(token):
        user = db.session.scalar(sa.select(Users).where(Users.token == token))
        if user is None or user.token_expiration.astimezone(timezone.utc) < datetime.now(timezone.utc):
            print(f"User: {user}")
            print(f"Current Time: {datetime.now(timezone.utc)}")
            return None
        return user

class COAIDtoGroup(db.Model):
    group_id = db.Column(db.Integer, primary_key=True, autoincrement=True)  # Explicitly define it
    group_name = db.Column(sa.String(128))

    # group_id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    # group_name: so.Mapped[str] = so.mapped_column(sa.String(128))

    # coa_entries = so.relationship("COA", back_populates="group")

    def __repr__(self):
        return '<COAIDtoGroup {}>'.format(self.group_id)

class COA(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    group_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(COAIDtoGroup.group_id), index=True)
    account: so.Mapped[str] = so.mapped_column(sa.String(256))

    # group = so.relationship("COAIDtoGroup", back_populates="coa_entries")
    # users = so.relationship("UserCOAAccess", back_populates="coa")

    def __repr__(self):
        return '<COA {}>'.format(self.account)

class UserCOAAccess(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Users.id), index=True)
    group_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(COAIDtoGroup.group_id), index=True)
    access_level: so.Mapped[Optional[str]] = so.mapped_column(sa.String(50))

    # coa = so.relationship("COA", back_populates="users")

    def __repr__(self):
        return '<UserCOAAccess {}>'.format(self.id)

class Template(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True, index=True)
    author: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Users.id), index=True)
    title: so.Mapped[str] = so.mapped_column(sa.String(256))
    model_name: so.Mapped[str] = so.mapped_column(sa.String(256), unique=True)
    coa_group_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(COAIDtoGroup.group_id), index=True)
    published: so.Mapped[bool] = so.mapped_column()
    active: so.Mapped[bool] = so.mapped_column()

    # Relationship mapping users who have access
    # users = so.relationship("UserTemplateAccess", back_populates="template")

    def __repr__(self):
        return '<Template {}>'.format(self.title)

    def from_dict(self, data):
        for field in ['author', 'title', 'model_name', 'coa_group_id', 'published', 'active']:
            if field in data:
                setattr(self, field, data[field])

class UserTemplateAccess(db.Model):
    template_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Template.id), primary_key=True, index=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Users.id), primary_key=True, index=True)
    access_level: so.Mapped[Optional[str]] = so.mapped_column(sa.String(50))

    # Reverse relationship back to Template
    # template = so.relationship("Template", back_populates="users")

    def __repr__(self):
        return '<UserTemplateAccess {}>'.format(self.access_level)


class Transaction(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    description: so.Mapped[str] = so.mapped_column(sa.String(500))
    account: so.Mapped[str] = so.mapped_column(sa.String(256))
    amount: so.Mapped[float] = so.mapped_column()
    template_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Template.id), index=True)

    def __repr__(self):
        return '<Transaction {}>'.format(self.description)

class Vendor(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    vendor: so.Mapped[str] = so.mapped_column(sa.String(256))
    transaction_descr: so.Mapped[str] = so.mapped_column(sa.String(500))
    template_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Template.id), index=True)

    def __repr__(self):
        return '<Vendor {}>'.format(self.vendor)

class MarketplaceTemplate(db.Model):
    template_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Template.id), index=True, primary_key=True)
    rating: so.Mapped[float] = so.mapped_column()
    price: so.Mapped[float] = so.mapped_column(index=True)
    description: so.Mapped[str] = so.mapped_column(sa.String(500))

    def __repr__(self):
        return f"<MarketplaceTemplate {self.template_id}>"

class MarketplaceTags(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    template_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Template.id), index=True)
    tag: so.Mapped[str] = so.mapped_column(sa.String(50), index=True)

    def __repr__(self):
        return f"<MarketplaceTags {self.template_id}>"

class NewVendorRequests(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    transaction_descr: so.Mapped[str] = so.mapped_column(sa.String(500))
    proposed_vendor: so.Mapped[str] = so.mapped_column(sa.String(256))
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Users.id), index=True)

    def __repr__(self):
        return f"<NewVendorRequests {self.id}>"
    

