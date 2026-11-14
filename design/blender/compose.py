# Composes final artwork from glyph_raw.png (Blender render) using Pillow/numpy.
import numpy as np, os
from PIL import Image, ImageDraw, ImageFilter, ImageChops
here=os.path.dirname(os.path.abspath(__file__)); out=os.path.join(here,"..","artwork"); os.makedirs(out,exist_ok=True)
S=512
glyph=Image.open(os.path.join(here,"glyph_raw.png")).convert("RGBA").resize((S,S),Image.LANCZOS)
def shadowed(g):
    a=g.getchannel("A")
    sh=Image.new("RGBA",(S,S),(0,18,90,0))
    sa=ImageChops.offset(a,0,12).filter(ImageFilter.GaussianBlur(14)).point(lambda v:int(v*0.34))
    sh.putalpha(sa)
    sh2=Image.new("RGBA",(S,S),(0,10,60,0))
    sa2=ImageChops.offset(a,0,3).filter(ImageFilter.GaussianBlur(3)).point(lambda v:int(v*0.18))
    sh2.putalpha(sa2)
    r=Image.alpha_composite(sh,sh2); return Image.alpha_composite(r,g)
gl=shadowed(glyph)
def gradient():
    y,x=np.mgrid[0:S,0:S]; t=((x+y)/(2*(S-1)))[...,None]
    c0=np.array([0x0A,0x84,0xFF],float); c1=np.array([0x00,0x40,0xDD],float)
    t=t**1.0
    a=c0*(1-t)+c1*t
    # soft top-left highlight
    d=np.sqrt((x-S*0.2)**2+(y-S*0.1)**2)/S; a=a+ (np.clip(0.55-d,0,1)[...,None])*np.array([20,20,0.0])*0.8
    return Image.fromarray(np.clip(a,0,255).astype(np.uint8),"RGB").convert("RGBA")
bg=gradient(); bg.save(os.path.join(out,"icon_bg.png"))
gl.save(os.path.join(out,"icon_fg.png"))
# squircle mask (superellipse blend of rounded rect), 4x supersample
K=4; m=Image.new("L",(S*K,S*K),0); ImageDraw.Draw(m).rounded_rectangle((0,0,S*K-1,S*K-1),radius=int(S*K*0.22),fill=255)
m=m.resize((S,S),Image.LANCZOS)
icon=bg.copy(); icon.putalpha(m); icon=Image.alpha_composite(icon,gl)
a=ImageChops.multiply(icon.getchannel("A"),m); icon.putalpha(a)
icon.save(os.path.join(out,"icon.png"))
# presplash
def splash(color,name,shadow):
    W,H=1080,2400; im=Image.new("RGBA",(W,H),color+(255,))
    w=280; ic=icon.resize((w*2,w*2),Image.LANCZOS) if False else icon.resize((w,w),Image.LANCZOS)
    x=(W-w)//2; y=int(H*0.5-w/2-H*0.04)
    if shadow:
        sh=Image.new("RGBA",(W,H),(0,0,0,0)); sa=Image.new("L",(W,H),0)
        sa.paste(ic.getchannel("A").point(lambda v:int(v*0.16)),(x,y+10)); sa=sa.filter(ImageFilter.GaussianBlur(14))
        sh=Image.new("RGBA",(W,H),(0,30,100,0)); sh.putalpha(sa); im=Image.alpha_composite(im,sh)
    im.alpha_composite(ic,(x,y)); im.convert("RGB").save(os.path.join(out,name))
splash((0xF2,0xF2,0xF7),"presplash.png",True); splash((0,0,0),"presplash_dark.png",False)
# bell
def bell(rgba,name):
    K=8; N=128*K; im=Image.new("RGBA",(N,N),(0,0,0,0)); d=ImageDraw.Draw(im)
    w=7*K; col=rgba
    import math
    pts=[]
    cx,cy,r=64,50,27
    for i in range(0,181,4):
        a=math.radians(180+i); pts.append((cx+r*math.cos(a),cy+r*math.sin(a)))
    pts+= [(91,70),(95,80),(102,86),(102,90),(26,90),(26,86),(33,80),(37,70)]
    pts.append(pts[0]); pts.append(pts[1])
    P=[(x*K,y*K) for x,y in pts]
    d.line(P,fill=col,width=w,joint="curve")
    for p in P[:-1:3]+[P[-2]]: d.ellipse((p[0]-w/2,p[1]-w/2,p[0]+w/2,p[1]+w/2),fill=col)
    d.ellipse(((64-4.5)*K,(19-4.5)*K,(64+4.5)*K,(19+4.5)*K),fill=col)
    d.arc((54*K,81*K,74*K,107*K),0,180,fill=col,width=w)
    for xx in (54,74):
        pass
    im=im.resize((128,128),Image.LANCZOS); im.save(os.path.join(out,name))
bell((0x0A,0x84,0xFF,255),"bell.png"); bell((255,255,255,230),"bell_dark.png")
# safe zone check
fa=np.array(gl.getchannel("A").point(lambda v:255 if v>20 else 0)); ys,xs=np.nonzero(fa)
rad=np.sqrt((xs-255.5)**2+(ys-255.5)**2).max(); print("fg max radius px (glyph+shadow)",rad,"limit 168")
g=np.array(glyph.getchannel("A")); ys,xs=np.nonzero(g>20); print("glyph bbox",xs.min(),xs.max(),ys.min(),ys.max(),"maxr",np.sqrt((xs-255.5)**2+(ys-255.5)**2).max())
