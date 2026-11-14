# Blender: renders the Modus glyph (transparent) -> glyph_raw.png (1024x1024, frame = 2 units wide)
import bpy, math, bmesh, sys, os
from mathutils import Vector
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glyph_raw.png")
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
R = 0.088      # tube radius
ZS = 0.55      # z flattening
pts = [(-0.60,-0.40),(-0.27,-0.04),(-0.04,-0.24),(0.40,0.30)]
# rounded corners
def fillet(p, rad):
    res=[p[0]]
    for i in range(1,len(p)-1):
        a,b,c=Vector(p[i-1]),Vector(p[i]),Vector(p[i+1])
        d1=(a-b).normalized(); d2=(c-b).normalized()
        r=min(rad,(a-b).length*0.45,(c-b).length*0.45)
        s=b+d1*r; e=b+d2*r
        for k in range(13):
            t=k/12
            q=(1-t)**2*s+2*t*(1-t)*b+t*t*e
            res.append((q.x,q.y))
    res.append(p[-1]); return res
path=fillet(pts,0.16)
cu=bpy.data.curves.new("line","CURVE"); cu.dimensions='3D'
cu.bevel_depth=R; cu.bevel_resolution=10; cu.resolution_u=12
sp=cu.splines.new('POLY'); sp.points.add(len(path)-1)
for i,(x,y) in enumerate(path): sp.points[i].co=(x,y,0,1)
mat=bpy.data.materials.new("w"); mat.use_nodes=True
b=mat.node_tree.nodes["Principled BSDF"]
b.inputs["Base Color"].default_value=(0.97,0.98,1,1); b.inputs["Roughness"].default_value=0.45
b.inputs["Specular IOR Level"].default_value=0.4
objs=[]
o=bpy.data.objects.new("line",cu); sc.collection.objects.link(o); objs.append(o)
def sphere(p,r):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r,segments=64,ring_count=32,location=(p[0],p[1],0))
    s=bpy.context.active_object; bpy.ops.object.shade_smooth(); objs.append(s)
sphere(path[0],R)
dpos=Vector(pts[-1])
sphere((dpos.x,dpos.y),R*1.7)
# center by bbox (tube radius included)
xs=[p[0] for p in path]+[dpos.x-R*1.7,dpos.x+R*1.7]; ys=[p[1] for p in path]+[dpos.y-R*1.7,dpos.y+R*1.7]
cx=(min(xs)+max(xs))/2; cy=(min(ys)+max(ys))/2
SC=float(os.environ.get("GSCALE","1.0"))
root=bpy.data.objects.new("root",None); sc.collection.objects.link(root)
for o in objs:
    o.parent=root; o.data.materials.append(mat)
    for p in (o,): pass
root.location=(-cx*SC,-cy*SC,0); root.scale=(SC,SC,SC*ZS)
# note: root scale z flatten; location offset compensates
# camera
cam=bpy.data.cameras.new("c"); cam.type='ORTHO'; cam.ortho_scale=2.0
co=bpy.data.objects.new("cam",cam); sc.collection.objects.link(co); co.location=(0,0,5); sc.camera=co
# lights
def area(loc,e,size,rot):
    l=bpy.data.lights.new("a","AREA"); l.energy=e; l.size=size
    ob=bpy.data.objects.new("a",l); sc.collection.objects.link(ob); ob.location=loc; ob.rotation_euler=rot
area((-2.5,3,4),350,4,(math.radians(-35),math.radians(-25),0))
area((2.5,-2,3),60,4,(math.radians(30),math.radians(25),0))
w=bpy.data.worlds.new("w"); sc.world=w; w.use_nodes=True
w.node_tree.nodes["Background"].inputs[0].default_value=(1,1,1,1); w.node_tree.nodes["Background"].inputs[1].default_value=0.55
sc.render.engine='CYCLES'; sc.cycles.samples=128; sc.cycles.use_denoising=True; sc.cycles.device='CPU'
sc.render.film_transparent=True
sc.render.resolution_x=1024; sc.render.resolution_y=1024; sc.render.resolution_percentage=100
sc.view_settings.view_transform='Standard'
sc.render.image_settings.file_format='PNG'; sc.render.image_settings.color_mode='RGBA'
sc.render.filepath=out
bpy.ops.render.render(write_still=True)
print("DONE",out)
