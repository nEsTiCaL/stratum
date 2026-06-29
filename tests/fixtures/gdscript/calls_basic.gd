func helper():
	return 1

func process():
	helper()
	self.cleanup()
	queue_free()

func cleanup():
	pass
