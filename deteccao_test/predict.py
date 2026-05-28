if __name__ == '__main__':
    from ultralytics import YOLO
    model = YOLO("detectorApple.pt")
    model(source='deteccao_test\Midias\IMG_5301.JPG', save=True, show_labels=False,show_conf=True,line_width=3,imgsz=640,show=False)
    