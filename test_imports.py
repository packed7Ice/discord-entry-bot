import numpy as np
import cv2
print("numpy:", np.__version__)
print("opencv:", cv2.__version__)
cap = cv2.VideoCapture(0)
print("camera opened:", cap.isOpened())
cap.release()
