from PIL import Image

img = Image.open("Icon.png")
img.save("specthr.ico", format='ICO', sizes=[(256, 256)])
