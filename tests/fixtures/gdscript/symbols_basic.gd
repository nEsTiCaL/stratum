extends Node
class_name Player

signal health_changed(amount)

const MAX_HP = 100
var hp = 100
var _secret = 0

@export var speed = 5.0

enum State { IDLE, RUN }

func _ready():
	pass

func take_damage(amount):
	hp -= amount

func _internal():
	pass

class Inner extends RefCounted:
	var x = 1
	func helper():
		return self.x
