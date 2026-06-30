extends "res://actors/base_actor.gd"
class_name Hero

const Bullet = preload("res://weapons/bullet.gd")
var menu = load("res://ui/menu.tscn")
var save = preload("user://save.dat")

func fire():
	var b = preload("res://weapons/bullet.gd").new()
