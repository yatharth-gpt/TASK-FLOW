import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from flask_socketio import SocketIO, join_room

app=Flask(__name__)
app.config.update(SECRET_KEY=os.getenv('SECRET_KEY','taskflow-secret'),SQLALCHEMY_DATABASE_URI='sqlite:///taskflow.db',SQLALCHEMY_TRACK_MODIFICATIONS=False,JWT_SECRET_KEY=os.getenv('JWT_SECRET_KEY','taskflow-jwt-secret'),JWT_ACCESS_TOKEN_EXPIRES=timedelta(days=7))
db=SQLAlchemy(app); jwt=JWTManager(app); CORS(app); socketio=SocketIO(app,cors_allowed_origins='*',async_mode='threading')
now=lambda:datetime.utcnow()
class User(db.Model):
 id=db.Column(db.Integer,primary_key=True); username=db.Column(db.String(80),unique=True,nullable=False); email=db.Column(db.String(120),unique=True,nullable=False); password_hash=db.Column(db.String(255),nullable=False); created_at=db.Column(db.DateTime,default=now)
class Task(db.Model):
 id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True); title=db.Column(db.String(200),nullable=False); description=db.Column(db.Text,default=''); notes=db.Column(db.Text,default=''); priority=db.Column(db.String(20),default='Medium'); status=db.Column(db.String(20),default='todo'); category=db.Column(db.String(50),default='General'); tag=db.Column(db.String(80),default=''); due_at=db.Column(db.DateTime); reminder_minutes=db.Column(db.Integer,default=0); important=db.Column(db.Boolean,default=False); created_at=db.Column(db.DateTime,default=now); updated_at=db.Column(db.DateTime,default=now,onupdate=now); completed_at=db.Column(db.DateTime)
 def out(self): return {'id':self.id,'title':self.title,'description':self.description or '','notes':self.notes or '','priority':self.priority,'status':self.status,'category':self.category or 'General','tag':self.tag or '','due_at':self.due_at.isoformat() if self.due_at else None,'reminder_minutes':self.reminder_minutes or 0,'important':bool(self.important),'created_at':self.created_at.isoformat() if self.created_at else None,'completed_at':self.completed_at.isoformat() if self.completed_at else None}
def uid(): return int(get_jwt_identity())
def parse_due(v): return datetime.fromisoformat(str(v).replace('Z','')) if v else None
def task(tid): return Task.query.filter_by(id=tid,user_id=uid()).first()
def changed(u): socketio.emit('tasks_changed',{'message':'updated'},room=f'user_{u}')
@app.route('/')
def home(): return render_template('index.html')
@app.get('/api/health')
def health(): return jsonify(status='ok',app='TaskFlow Pro')
@app.post('/api/auth/register')
def register():
 d=request.get_json() or {}; n=str(d.get('username','')).strip(); e=str(d.get('email','')).strip().lower(); p=str(d.get('password',''))
 if not n or not e or not p:return jsonify(error='All fields are required'),400
 if len(p)<6:return jsonify(error='Password must be at least 6 characters'),400
 if User.query.filter((User.email==e)|(User.username==n)).first():return jsonify(error='Username or email already exists'),409
 u=User(username=n,email=e,password_hash=generate_password_hash(p));db.session.add(u);db.session.commit();return jsonify(token=create_access_token(identity=str(u.id)),user={'id':u.id,'username':n,'email':e}),201
@app.post('/api/auth/login')
def login():
 d=request.get_json() or {};u=User.query.filter_by(email=str(d.get('email','')).strip().lower()).first()
 if not u or not check_password_hash(u.password_hash,str(d.get('password',''))):return jsonify(error='Invalid email or password'),401
 return jsonify(token=create_access_token(identity=str(u.id)),user={'id':u.id,'username':u.username,'email':u.email})
@app.get('/api/me')
@jwt_required()
def me():
 u=User.query.get(uid());return jsonify(id=u.id,username=u.username,email=u.email,created_at=u.created_at.isoformat())
@app.put('/api/me')
@jwt_required()
def edit_me():
 u=User.query.get(uid());d=request.get_json() or {};n=str(d.get('username',u.username)).strip();e=str(d.get('email',u.email)).strip().lower()
 if not n or not e:return jsonify(error='Username and email are required'),400
 if User.query.filter(User.id!=u.id,(User.email==e)|(User.username==n)).first():return jsonify(error='Username or email is already in use'),409
 u.username=n;u.email=e;db.session.commit();return me()
@app.get('/api/tasks')
@jwt_required()
def tasks():return jsonify([t.out() for t in Task.query.filter_by(user_id=uid()).order_by(Task.created_at.desc()).all()])
@app.post('/api/tasks')
@jwt_required()
def add():
 d=request.get_json() or {};title=str(d.get('title','')).strip()
 if not title:return jsonify(error='Task title is required'),400
 try:due=parse_due(d.get('due_at'))
 except: return jsonify(error='Invalid due date/time'),400
 t=Task(user_id=uid(),title=title,description=d.get('description',''),notes=d.get('notes',''),priority=d.get('priority','Medium'),status=d.get('status','todo'),category=d.get('category','General'),tag=d.get('tag',''),due_at=due,reminder_minutes=int(d.get('reminder_minutes',0) or 0),important=bool(d.get('important',False)))
 if t.status=='done':t.completed_at=now()
 db.session.add(t);db.session.commit();changed(t.user_id);return jsonify(t.out()),201
@app.put('/api/tasks/<int:tid>')
@jwt_required()
def edit(tid):
 t=task(tid)
 if not t:return jsonify(error='Task not found'),404
 d=request.get_json() or {}
 for f in ['title','description','notes','priority','status','category','tag','important']:
  if f in d:setattr(t,f,d[f])
 if 'due_at' in d:
  try:t.due_at=parse_due(d['due_at'])
  except:return jsonify(error='Invalid due date/time'),400
 if 'reminder_minutes' in d:t.reminder_minutes=int(d['reminder_minutes'] or 0)
 if t.status=='done' and not t.completed_at:t.completed_at=now()
 if t.status!='done':t.completed_at=None
 db.session.commit();changed(t.user_id);return jsonify(t.out())
@app.delete('/api/tasks/<int:tid>')
@jwt_required()
def delete(tid):
 t=task(tid)
 if not t:return jsonify(error='Task not found'),404
 u=t.user_id;db.session.delete(t);db.session.commit();changed(u);return jsonify(ok=True)
@app.get('/api/stats')
@jwt_required()
def stats():
 ts=Task.query.filter_by(user_id=uid()).all();total=len(ts);done=sum(t.status=='done' for t in ts);over=sum(bool(t.due_at and t.status!='done' and t.due_at<now()) for t in ts);return jsonify(total=total,completed=done,pending=total-done,overdue=over,important=sum(t.important and t.status!='done' for t in ts),progress=round(done/total*100) if total else 0)
@app.get('/api/analytics')
@jwt_required()
def analytics():
 ts=Task.query.filter_by(user_id=uid()).all();cats={}
 for t in ts:cats[t.category or 'General']=cats.get(t.category or 'General',0)+1
 return jsonify(status={s:sum(t.status==s for t in ts) for s in ['todo','in-progress','done']},priority={p:sum(t.priority==p for t in ts) for p in ['Low','Medium','High','Urgent']},categories=cats)
@socketio.on('join_user')
def join(data):
 if data and data.get('user_id'):join_room(f"user_{data['user_id']}")
with app.app_context():db.create_all()
if __name__=='__main__':socketio.run(app,host='0.0.0.0',port=5000,debug=True,allow_unsafe_werkzeug=True)
